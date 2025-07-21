# core.py
import os
import sqlite3
import logging
import subprocess
import platform
import shutil # MODIFIÉ : Ajout de shutil pour un déplacement de fichier plus robuste
from pikepdf import Pdf, Page, PdfError
from PIL import Image

# --- Statuts et Extensions ---
STATUS = {
    'QUEUED': 'EN_ATTENTE_TRAITEMENT',
    'CONVERTING': 'CONVERSION_EN_COURS',
    'COUNTING': 'COMPTAGE_PAGES',
    'READY': 'PRET_POUR_CALCUL',
    'READY_NO_PAGE_COUNT': 'PRET_SANS_COMPTAGE',
    'PRINTING': 'IMPRESSION_EN_COURS',
    'PRINT_SUCCESS': 'IMPRIME_AVEC_SUCCES',
    'PRINT_SUCCESS_NO_COUNT': 'IMPRIME_SANS_COMPTAGE',
    'PRINT_FAILED': 'ECHEC_IMPRESSION',
    'ERROR_CONVERSION': 'ERREUR_CONVERSION',
    'ERROR_PAGE_COUNT': 'ERREUR_COMPTAGE_PAGES',
    'ERROR_FILE_EMPTY': 'ERREUR_FICHIER_VIDE',
    'ERROR_FATAL_READ': 'ERREUR_LECTURE_FATALE'
}
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'txt'}

# --- Fonctions de Base de Données ---
def get_db_connection(db_file):
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    return conn

def db_update_task(db_file, task_id, update_data):
    """Met à jour une tâche dans la base de données."""
    with get_db_connection(db_file) as conn:
        set_clause = ', '.join([f'{key} = ?' for key in update_data.keys()])
        values = list(update_data.values())
        values.append(task_id)
        query = f"UPDATE history SET {set_clause} WHERE task_id = ?"
        conn.execute(query, tuple(values))
        conn.commit()

# MODIFIÉ : Correction majeure de la fonction pour garantir l'ordre des données.
def db_insert_task(db_file, task_data):
    """Insère une nouvelle tâche dans la base de données de manière sécurisée."""
    with get_db_connection(db_file) as conn:
        columns = list(task_data.keys())
        values = [task_data[col] for col in columns] # Garantit que l'ordre des valeurs correspond aux colonnes

        columns_str = ', '.join(columns)
        placeholders_str = ', '.join('?' * len(columns))

        query = f"INSERT INTO history ({columns_str}) VALUES ({placeholders_str})"
        conn.execute(query, tuple(values))
        conn.commit()

# --- Fonctions de Traitement de Fichier ---
def convert_to_pdf(original_path, output_dir, config):
    """Convertit un fichier en PDF en utilisant LibreOffice."""
    if not os.path.exists(config['LIBREOFFICE_PATH']):
        logging.error("LibreOffice n'est pas trouvé. Impossible de convertir le fichier.")
        return None

    command = [
        config['LIBREOFFICE_PATH'],
        '--headless',
        '--convert-to', 'pdf',
        '--outdir', output_dir,
        original_path
    ]
    try:
        subprocess.run(command, check=True, timeout=25, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pdf_filename = f"{os.path.splitext(os.path.basename(original_path))[0]}.pdf"
        return os.path.join(output_dir, pdf_filename)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logging.error(f"Erreur de conversion LibreOffice pour {original_path}: {e}")
        return None

def count_pdf_pages(pdf_path):
    """Compte le nombre de pages dans un fichier PDF."""
    try:
        # Ajout d'une vérification pour les fichiers de 0 octet qui peuvent causer des erreurs
        if os.path.getsize(pdf_path) == 0:
            logging.warning(f"Le fichier PDF {pdf_path} est vide (0 octet).")
            return 0
        with Pdf.open(pdf_path) as pdf:
            return len(pdf.pages)
    except PdfError as e:
        logging.error(f"Erreur PikePDF lors du comptage des pages de {pdf_path}: {e}")
        return 0
    except FileNotFoundError:
        logging.error(f"Fichier PDF non trouvé pour le comptage: {pdf_path}")
        return 0

def process_single_file_background(thread_args, config):
    """Fonction exécutée en arrière-plan pour traiter un fichier."""
    task_id = thread_args['task_id']
    original_path = thread_args['original_path']
    secure_filename = thread_args['secure_filename']
    db_file = config['DATABASE_FILE']

    # Vérification initiale de l'existence du fichier
    if not original_path or not os.path.exists(original_path):
        logging.error(f"Fichier original non trouvé pour la tâche {task_id} au chemin : {original_path}")
        db_update_task(db_file, task_id, {'status': STATUS['ERROR_FATAL_READ']})
        return

    try:
        ext = os.path.splitext(original_path)[1].lower()
        final_pdf_path = None

        if ext == '.pdf':
            final_pdf_path = os.path.join(config['CONVERTED_FOLDER'], f"{os.path.splitext(secure_filename)[0]}.pdf")
            # MODIFIÉ : Utilisation de shutil.move pour plus de robustesse
            shutil.move(original_path, final_pdf_path)
        elif ext in {'.jpg', '.jpeg', '.png'}:
            db_update_task(db_file, task_id, {'status': STATUS['CONVERTING']})
            image = Image.open(original_path)
            if image.mode == 'RGBA':
                image = image.convert('RGB')
            pdf_path_temp = os.path.join(config['CONVERTED_FOLDER'], f"{os.path.splitext(secure_filename)[0]}.pdf")
            image.save(pdf_path_temp, "PDF", resolution=100.0)
            final_pdf_path = pdf_path_temp
        else:
            db_update_task(db_file, task_id, {'status': STATUS['CONVERTING']})
            final_pdf_path = convert_to_pdf(original_path, config['CONVERTED_FOLDER'], config)

        if not final_pdf_path or not os.path.exists(final_pdf_path):
            db_update_task(db_file, task_id, {'status': STATUS['ERROR_CONVERSION']})
            return

        # MODIFIÉ : Mise à jour du chemin dans la BDD pour pointer vers le fichier traité
        db_update_task(db_file, task_id, {'status': STATUS['COUNTING'], 'original_path': final_pdf_path})
        num_pages = count_pdf_pages(final_pdf_path)

        if num_pages > 0:
            db_update_task(db_file, task_id, {'status': STATUS['READY'], 'pages': num_pages})
        else:
            # Si le comptage échoue, on met un statut d'erreur, sauf si le fichier était déjà un PDF
            # (certains PDF de 1 page peuvent être mal interprétés par les compteurs)
            if ext == '.pdf':
                 db_update_task(db_file, task_id, {'status': STATUS['READY_NO_PAGE_COUNT'], 'pages': 0})
            else:
                 db_update_task(db_file, task_id, {'status': STATUS['ERROR_PAGE_COUNT'], 'pages': 0})

    except Exception as e:
        logging.error(f"Erreur fatale lors du traitement de {original_path} (tâche {task_id}): {e}", exc_info=True)
        db_update_task(db_file, task_id, {'status': STATUS['ERROR_FATAL_READ']})
