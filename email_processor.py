# email_processor.py
import imaplib
import email
from email.header import decode_header
import os
import time
import uuid
import logging
from datetime import datetime, timedelta
import threading  # MODIFIÉ : Ajout de l'import manquant

from core import db_insert_task, process_single_file_background, get_db_connection, ALLOWED_EXTENSIONS, STATUS
from werkzeug.utils import secure_filename

def get_config_from_context(app_context):
    """Extrait la configuration de l'application depuis son contexte."""
    with app_context():
        from flask import current_app
        return current_app.config

def decode_subject(encoded_subject):
    """Décode le sujet d'un email, même s'il contient des caractères spéciaux."""
    if not encoded_subject:
        return ""
    try:
        decoded_parts = decode_header(encoded_subject)
        subject = ""
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                subject += part.decode(encoding or 'utf-8', 'ignore')
            else:
                subject += part
        return subject
    except Exception:
        return str(encoded_subject) # En cas d'erreur, retourne la version brute

def check_emails(config):
    """Vérifie la boîte mail, télécharge les pièces jointes et les traite."""
    try:
        mail = imaplib.IMAP4_SSL(config['EMAIL_IMAP_SERVER'])
        mail.login(config['EMAIL_ADDRESS'], config['EMAIL_APP_PASSWORD'])
        mail.select('inbox')
        mail.list() # Liste des dossiers

        # Créer le dossier pour les emails traités s'il n'existe pas
        processed_mailbox = config['EMAIL_PROCESSED_MAILBOX']
        mail.create(processed_mailbox) # Ne fait rien s'il existe déjà

        status, messages = mail.search(None, 'UNSEEN') # Cherche les emails non lus
        if status != 'OK':
            logging.error("Erreur lors de la recherche d'emails.")
            return

        for num in messages[0].split():
            status, data = mail.fetch(num, '(RFC822)')
            if status != 'OK':
                logging.error(f"Erreur lors de la récupération de l'email {num}.")
                continue

            msg = email.message_from_bytes(data[0][1])

            sender = msg.get('From')
            sender_email = email.utils.parseaddr(sender)[1]
            subject = decode_subject(msg.get('Subject'))

            logging.info(f"Nouvel email détecté de '{sender_email}' avec le sujet '{subject}'")

            conn = get_db_connection(config['DATABASE_FILE'])
            cursor = conn.cursor()

            # Logique pour regrouper les emails récents du même expéditeur
            time_threshold = (datetime.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                """SELECT job_id FROM history
                   WHERE client_name = ? AND source = 'email' AND timestamp >= ?
                   ORDER BY timestamp DESC LIMIT 1""",
                (sender_email, time_threshold)
            )
            existing_job = cursor.fetchone()

            if existing_job:
                job_id = existing_job['job_id']
                logging.info(f"Email de {sender_email} regroupé avec le job existant {job_id}.")
            else:
                job_id = f"email-{int(time.time())}-{uuid.uuid4().hex[:6]}"
                logging.info(f"Nouveau job {job_id} créé pour l'email de {sender_email}.")

            conn.close()

            found_attachments = False
            for part in msg.walk():
                if part.get_content_maintype() == 'multipart' or part.get('Content-Disposition') is None:
                    continue

                filename = part.get_filename()
                if filename:
                    filename = decode_subject(filename)
                    if any(filename.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS):
                        found_attachments = True
                        timestamp = int(time.time())
                        original_secure_name = secure_filename(filename)
                        unique_filename = f"{timestamp}_{uuid.uuid4().hex[:8]}_{original_secure_name}"
                        filepath = os.path.join(config['EMAIL_FOLDER'], unique_filename)

                        with open(filepath, 'wb') as f:
                            f.write(part.get_payload(decode=True))
                        logging.info(f"Pièce jointe '{filename}' sauvegardée dans '{filepath}'")

                        task_id = f"task-{int(time.time())}-{uuid.uuid4().hex[:8]}"
                        task_data = {
                            'job_id': job_id,
                            'task_id': task_id,
                            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            'client_name': sender_email,
                            'file_name': filename,
                            'secure_filename': unique_filename,
                            'status': STATUS['QUEUED'],
                            'source': 'email',
                            'email_subject': subject,
                            'original_path': filepath
                        }

                        db_insert_task(config['DATABASE_FILE'], task_data)

                        thread_args = {
                            'task_id': task_id,
                            'original_path': filepath,
                            'secure_filename': unique_filename
                        }
                        thread = threading.Thread(target=process_single_file_background, args=(thread_args, config))
                        thread.start()

            if found_attachments:
                # Marquer l'email comme lu et le déplacer
                mail.store(num, '+FLAGS', '\\Seen')
                mail.copy(num, processed_mailbox)
                mail.store(num, '+FLAGS', '\\Deleted')

        mail.expunge() # Appliquer les suppressions
        mail.logout()

    except Exception as e:
        logging.error(f"Erreur critique dans le processeur d'emails: {e}", exc_info=True)


def check_emails_periodically(config_obj, app_context):
    """Boucle infinie qui vérifie les emails à intervalle régulier."""
    config = get_config_from_context(app_context)
    logging.info("Le service de surveillance des emails est démarré.")
    while True:
        try:
            check_emails(config)
        except Exception as e:
            logging.error(f"Erreur dans la boucle de surveillance des emails: {e}")
        time.sleep(config.get('EMAIL_CHECK_INTERVAL', 30))
