# config.py
import os
import platform

# Chemin de la racine du projet
basedir = os.path.abspath(os.path.dirname(__file__))

def find_libreoffice_path():
    """Tente de trouver le chemin de l'exécutable de LibreOffice."""
    system = platform.system()
    if system == "Windows":
        return "C:\\Program Files\\LibreOffice\\program\\soffice.exe"
    elif system == "Darwin": # macOS
        return "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    elif system == "Linux":
        return "/usr/bin/libreoffice"
    return None

class Config:
    # --- Clé secrète et Identifiants ---
    # Pour la production, définissez ces variables dans votre environnement !
    # Exemple : export SECRET_KEY='une-vraie-cle-secrete-tres-longue'
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'session_impression_finale_2025_admin_super_secret'
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME') or 'admin'
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD') or '4187'
    TASK_PROCESSING_TIMEOUT = 30 # en secondes

    # --- Configuration de l'impression ---
    PRINTER_IP = os.environ.get('PRINTER_IP') or '192.168.1.18:8000'
    PRIX_NOIR_BLANC = 0.20
    PRIX_COULEUR = 0.70

    # --- Configuration de la boîte mail ---
    EMAIL_IMAP_SERVER = 'imap.gmail.com'
    EMAIL_ADDRESS = os.environ.get('EMAIL_ADDRESS') or 'latelier0000@gmail.com'
    EMAIL_APP_PASSWORD = os.environ.get('EMAIL_APP_PASSWORD') or 'tiwt ipas vtad hbib'
    # MODIFIÉ : Intervalle réduit à 10 secondes
    EMAIL_CHECK_INTERVAL = 10
    EMAIL_PROCESSED_MAILBOX = 'Traités' # Nom du dossier où déplacer les emails traités

    # --- Chemins des fichiers et dossiers ---
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    CONVERTED_FOLDER = os.path.join(UPLOAD_FOLDER, 'converted')
    EMAIL_FOLDER = os.path.join(UPLOAD_FOLDER, 'emails') # Dossier pour les pièces jointes
    DATABASE_FILE = os.path.join(basedir, 'history.db')

    # --- Dépendances externes ---
    LIBREOFFICE_PATH = os.environ.get('LIBREOFFICE_PATH') or find_libreoffice_path()

    # --- URL de l'imprimante ---
    URL_PDF_PRINT = f"http://{PRINTER_IP}/direct"
