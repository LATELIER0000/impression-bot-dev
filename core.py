# core.py
import os
import shutil
import subprocess
import time
import pathlib
import sqlite3
import logging
from multiprocessing import Process, Queue

from PyPDF2 import PdfReader, errors as PyPDF2Errors
from werkzeug.utils import secure_filename

# On ne peut pas importer la config de Flask directement pour éviter les dépendances.
# On la passera en argument des fonctions.
# Cependant, on peut définir les constantes ici.

STATUS = {
    'UPLOADING': 'TELECHARGEMENT_EN_COURS', 'QUEUED': 'EN_ATTENTE_TRAITEMENT',
    'CONVERTING': 'CONVERSION_EN_COURS', 'COUNTING': 'COMPTAGE_PAGES',
    'ERROR_FILE_EMPTY': 'ERREUR_FICHIER_VIDE',
    'ERROR_CONVERSION': 'ERREUR_CONVERSION',
    'ERROR_PAGE_COUNT': 'ERREUR_COMPTAGE_PAGES',
    'ERROR_FATAL_READ': 'ERREUR_LECTURE_FATALE',
    'READY': 'PRET_POUR_CALCUL',
    'READY_NO_PAGE_COUNT': 'PRET_SANS_COMPTAGE',
    'PRINTING': 'IMPRESSION_EN_COURS',
    'PRINT_SUCCESS': 'IMPRIME_AVEC_SUCCES',
    'PRINT_SUCCESS_NO_COUNT': 'IMPRIME_SANS_COMPTAGE',
    'PRINT_FAILED': 'ERREUR_IMPRESSION'
}

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'txt'}

def get_db_connection(database_file):
    conn = sqlite3.connect(database_file, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def db_update_task(database_file, task_id, data):
    with get_db_connection(database_file) as conn:
        fields = ', '.join([f'{key} = ?' for key in data.keys()])
        values = list(data.values()) + [task_id]
        query = f"UPDATE history SET {fields} WHERE task_id = ?"
        conn.execute(query, tuple(values))
        conn.commit()

def db_insert_task(database_file, data):
    with get_db_connection(database_file) as conn:
        columns = ['job_id', 'task_id', 'timestamp', 'client_name', 'file_name', 'secure_filename', 'status', 'pages', 'copies', 'color', 'duplex', 'price', 'paper_size', 'page_mode', 'start_page', 'end_page', 'source', 'email_subject', 'original_path']
        query_cols = ', '.join(columns)
        placeholders = ', '.join(['?'] * len(columns))
        values = [data.get(col) for col in columns]
        query = f"INSERT INTO history ({query_cols}) VALUES ({placeholders})"
        conn.execute(query, tuple(values))
        conn.commit()

def count_pages(filepath):
    try:
        with open(filepath, 'rb') as f:
            reader = PdfReader(f)
            if reader.is_encrypted:
                logging.warning(f"Le fichier PDF {filepath} est chiffré.")
            return len(reader.pages) if reader.pages else 0
    except PyPDF2Errors.PdfReadError as e:
        logging.error(f"Erreur de lecture PDF (PyPDF2) pour {filepath}: {e}")
        return 0
    except Exception as e:
        logging.error(f"Erreur générique lors du comptage des pages pour {filepath}: {e}")
        return 0

def count_pages_worker(filepath, result_queue):
    try:
        page_count = count_pages(filepath)
        result_queue.put(page_count)
    except Exception as e:
        logging.error(f"Erreur inattendue dans le worker count_pages pour {filepath}: {e}")
        result_queue.put(-1)

def convert_to_pdf(source_path, secure_filename, converted_folder, libreoffice_path):
    pdf_filename = f"{os.path.splitext(secure_filename)[0]}.pdf"
    pdf_path = os.path.join(converted_folder, pdf_filename)
    if source_path.lower().endswith('.pdf'):
        shutil.copy(source_path, pdf_path)
        return pdf_path
    lo_command = libreoffice_path
    if not lo_command or not os.path.exists(lo_command):
        logging.error(f"Chemin de LibreOffice non configuré ou invalide: {lo_command}")
        return None
    user_profile_path = os.path.join(os.getcwd(), 'lo_profile', str(time.time_ns()))
    os.makedirs(user_profile_path, exist_ok=True)
    user_profile_url = pathlib.Path(user_profile_path).as_uri()
    try:
        command = [lo_command, f'-env:UserInstallation={user_profile_url}', '--headless', '--convert-to', 'pdf:writer_pdf_Export', '--outdir', converted_folder, source_path]
        subprocess.run(command, check=True, timeout=120)
        timeout = 20
        start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                time.sleep(1)
                return pdf_path
            time.sleep(0.5)
        logging.error(f"La conversion a réussi mais le fichier PDF n'a pas été trouvé à temps: {pdf_path}")
        return None
    except Exception as e:
        logging.error(f"Erreur de conversion LibreOffice: {e}")
        return None
    finally:
        shutil.rmtree(user_profile_path, ignore_errors=True)

def process_single_file_background(task_info, config):
    task_id = task_info['task_id']; original_filepath = task_info['original_path']; secure_name_for_conversion = task_info['secure_filename']
    db_file = config['DATABASE_FILE']
    converted_folder = config['CONVERTED_FOLDER']
    lo_path = config['LIBREOFFICE_PATH']

    db_update_task(db_file, task_id, {'status': STATUS['CONVERTING'], 'timestamp': time.strftime("%Y-%m-%d %H:%M:%S")})
    final_pdf_path = convert_to_pdf(original_filepath, secure_name_for_conversion, converted_folder, lo_path)
    if not final_pdf_path:
        logging.error(f"Échec de conversion pour {secure_name_for_conversion}")
        db_update_task(db_file, task_id, {'status': STATUS['ERROR_CONVERSION']}); return

    db_update_task(db_file, task_id, {'status': STATUS['COUNTING']})

    result_queue = Queue()
    process = Process(target=count_pages_worker, args=(final_pdf_path, result_queue))
    process.start()
    process.join(timeout=15)

    if process.is_alive():
        process.terminate()
        process.join()
        logging.error(f"Le comptage des pages pour {final_pdf_path} a dépassé le timeout. Crash probable.")
        db_update_task(db_file, task_id, {'status': STATUS['ERROR_FATAL_READ'], 'pages': 0})
        return

    if process.exitcode != 0:
        logging.error(f"Le processus de comptage a crashé pour {final_pdf_path} (exit code: {process.exitcode}).")
        db_update_task(db_file, task_id, {'status': STATUS['ERROR_FATAL_READ'], 'pages': 0})
        return

    try:
        pages = result_queue.get_nowait()
    except Exception:
        logging.error(f"Impossible de récupérer le résultat du processus de comptage pour {final_pdf_path}.")
        db_update_task(db_file, task_id, {'status': STATUS['ERROR_FATAL_READ'], 'pages': 0})
        return

    if pages > 0:
        db_update_task(db_file, task_id, {'pages': pages, 'status': STATUS['READY']})
        logging.info(f"Fichier {secure_name_for_conversion} prêt pour calcul ({pages} pages).")
    else:
        logging.warning(f"Échec du comptage de pages pour {final_pdf_path}. Passage en mode 'Prêt sans comptage'.")
        db_update_task(db_file, task_id, {'pages': 0, 'status': STATUS['READY_NO_PAGE_COUNT']})
