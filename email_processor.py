# email_processor.py
import email
import imaplib
import os
import time
import logging
import traceback
import uuid
import threading
from datetime import datetime, timedelta # On importe timedelta
from email.header import decode_header
from werkzeug.utils import secure_filename

# NOUVEL IMPORT depuis core.py
from core import db_insert_task, process_single_file_background, STATUS

log = logging.getLogger('email_processor')
log.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - [EMAIL_PROCESSOR] - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
if not log.handlers:
    log.addHandler(handler)

def connect_to_mailbox(config):
    try:
        imap_conn = imaplib.IMAP4_SSL(config['EMAIL_IMAP_SERVER'])
        imap_conn.login(config['EMAIL_ADDRESS'], config['EMAIL_APP_PASSWORD'])
        log.info(f"Connecté avec succès à la boîte mail {config['EMAIL_ADDRESS']}")
        return imap_conn
    except Exception as e:
        log.error(f"Échec de la connexion à la boîte mail: {e}")
        return None

def ensure_mailbox_exists(imap_conn, mailbox_name):
    status, mailboxes = imap_conn.list()
    if status == 'OK':
        for m in mailboxes:
            # On doit décoder le nom du dossier reçu, qui est en utf-7
            try:
                decoded_mailbox_path = m.decode('utf-7').split(' "/" ')[-1].strip('"')
            except:
                decoded_mailbox_path = m.decode('latin-1').split(' "/" ')[-1].strip('"')

            if mailbox_name.lower() == decoded_mailbox_path.lower():
                log.info(f"Le dossier '{mailbox_name}' existe déjà.")
                return True
        log.info(f"Le dossier '{mailbox_name}' n'existe pas, tentative de création...")
        try:
            # CORRIGÉ : On encode le nom du dossier en 'utf-7'
            status, response = imap_conn.create(mailbox_name.encode('utf-7'))
            if status == 'OK':
                log.info(f"Dossier '{mailbox_name}' créé avec succès.")
                return True
            else:
                log.error(f"Impossible de créer le dossier '{mailbox_name}': {response[0].decode()}")
                return False
        except Exception as e:
            log.error(f"Erreur lors de la création du dossier '{mailbox_name}': {e}")
            return False
    return False

def process_email(email_id, msg, flask_app_config):
    subject, encoding = decode_header(msg['Subject'])[0]
    if isinstance(subject, bytes): subject = subject.decode(encoding if encoding else 'utf-8')

    sender_full = msg.get('From')
    sender_email = email.utils.parseaddr(sender_full)[1] or sender_full

    log.info(f"Traitement de l'email de: {sender_email}, Sujet: {subject}")

    job_id = f"email-{int(time.time())}-{uuid.uuid4().hex[:6]}"

    attachments = []

    for part in msg.walk():
        content_type = part.get_content_type()
        content_disposition = str(part.get("Content-Disposition"))

        if content_type == 'text/plain' and 'attachment' not in content_disposition:
            try:
                body_content = part.get_payload(decode=True).decode()
                if body_content.strip():
                    attachments.append({'is_body': True, 'content': body_content, 'filename': 'corps_email.txt'})
            except Exception as e:
                log.error(f"Impossible de décoder le corps de l'email: {e}")
            continue

        if 'attachment' in content_disposition:
            filename = part.get_filename()
            if filename:
                decoded_filename, charset = decode_header(filename)[0]
                if isinstance(decoded_filename, bytes):
                    filename = decoded_filename.decode(charset if charset else 'utf-8')
                attachments.append({'is_body': False, 'content': part.get_payload(decode=True), 'filename': filename})

    if not attachments:
        log.warning(f"L'email de {sender_email} (sujet: '{subject}') ne contient ni pièce jointe ni corps de texte valide. Ignoré.")
        return

    for attachment in attachments:
        original_filename = attachment['filename']
        secure_name = f"{os.path.splitext(secure_filename(original_filename))[0]}_{uuid.uuid4().hex[:4]}{os.path.splitext(original_filename)[1]}"
        filepath = os.path.join(flask_app_config['EMAIL_FOLDER'], secure_name)

        try:
            with open(filepath, 'wb' if not attachment['is_body'] else 'w', encoding=('utf-8' if attachment['is_body'] else None)) as f:
                f.write(attachment['content'])
        except Exception as e:
            log.error(f"Impossible de sauvegarder le fichier {original_filename}: {e}")
            continue

        task_id = f"task-{uuid.uuid4().hex}"
        task_data = {
            'job_id': job_id, 'task_id': task_id, 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'client_name': sender_email, 'file_name': original_filename, 'secure_filename': secure_name,
            'status': STATUS['QUEUED'], 'source': 'email', 'email_subject': subject, 'original_path': filepath
        }
        db_insert_task(flask_app_config['DATABASE_FILE'], task_data)
        log.info(f"Tâche {task_id} créée pour le fichier {original_filename} du job {job_id}")

        thread_args = {'task_id': task_id, 'original_path': filepath, 'secure_filename': secure_name}
        process_thread = threading.Thread(target=process_single_file_background, args=(thread_args, flask_app_config))
        process_thread.start()

def check_emails_periodically(flask_app_config, app_context):
    config = flask_app_config
    log.info("Le service de surveillance des emails est démarré.")
    while True:
        imap_conn = None
        try:
            imap_conn = connect_to_mailbox(config)
            if not imap_conn:
                log.warning(f"Connexion échouée, nouvelle tentative dans {config['EMAIL_CHECK_INTERVAL']} secondes.")
                time.sleep(config['EMAIL_CHECK_INTERVAL'])
                continue

            ensure_mailbox_exists(imap_conn, config['EMAIL_PROCESSED_MAILBOX'])
            imap_conn.select('INBOX')

            # --- MODIFICATION ---
            # Calcule la date d'il y a 7 jours
            date_since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
            # Construit le critère de recherche
            search_criteria = f'(UNSEEN SINCE "{date_since}")'
            log.info(f"Recherche des emails non lus depuis le {date_since}...")

            # Utilise le nouveau critère
            status, messages = imap_conn.search(None, search_criteria)
            # --------------------

            if status == 'OK':
                email_ids = messages[0].split()
                if not email_ids:
                    log.info("Aucun nouvel email récent. En attente...")
                else:
                    log.info(f"Trouvé {len(email_ids)} nouvel(s) email(s) récent(s).")
                    for email_id in email_ids:
                        status_fetch, msg_data = imap_conn.fetch(email_id, '(RFC822)')
                        if status_fetch == 'OK':
                            msg = email.message_from_bytes(msg_data[0][1])
                            with app_context():
                                process_email(email_id, msg, config)
                            # On encode aussi pour la commande COPY avec 'utf-7'
                            imap_conn.copy(email_id, config['EMAIL_PROCESSED_MAILBOX'].encode('utf-7'))
                            imap_conn.store(email_id, '+FLAGS', '\\Deleted')
                    imap_conn.expunge()
            imap_conn.logout()
        except Exception as e:
            log.error(f"Une erreur est survenue dans la boucle de surveillance: {traceback.format_exc()}")
            if imap_conn:
                try: imap_conn.logout()
                except: pass

        time.sleep(config['EMAIL_CHECK_INTERVAL'])
