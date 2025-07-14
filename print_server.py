# print_server.py
import os
import time
import sys
import subprocess
import shutil
from datetime import datetime, timedelta
import pathlib
from collections import OrderedDict
import threading
import uuid
import sqlite3
import logging
import traceback

import click
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory, g
from PyPDF2 import PdfReader
from werkzeug.utils import secure_filename

from config import Config
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
app.config.from_object(Config)

STATUS = {
    'UPLOADING': 'TELECHARGEMENT_EN_COURS', 'QUEUED': 'EN_ATTENTE_TRAITEMENT',
    'CONVERTING': 'CONVERSION_EN_COURS', 'COUNTING': 'COMPTAGE_PAGES',
    'ERROR_CONVERSION': 'ERREUR_CONVERSION', 'ERROR_PAGE_COUNT': 'ERREUR_COMPTAGE_PAGES',
    'READY': 'PRET_POUR_CALCUL', 'PRINTING': 'IMPRESSION_EN_COURS',
    'PRINT_SUCCESS': 'IMPRIME_AVEC_SUCCES', 'PRINT_FAILED': 'ERREUR_IMPRESSION'
}
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods'}

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE_FILE'], detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = get_db()
    with app.open_resource('schema.sql', mode='r') as f:
        db.cursor().executescript(f.read())
    db.commit()
    logging.info("Base de données initialisée avec le schéma.")

def db_update_task(task_id, data):
    db = get_db()
    fields = ', '.join([f'{key} = ?' for key in data.keys()])
    values = list(data.values())
    values.append(task_id)
    query = f"UPDATE history SET {fields} WHERE task_id = ?"
    db.execute(query, tuple(values))
    db.commit()

def db_insert_task(data):
    db = get_db()
    columns = ['job_id', 'task_id', 'timestamp', 'client_name', 'file_name', 'secure_filename', 'status', 'pages', 'copies', 'color', 'duplex', 'price', 'paper_size', 'page_mode', 'start_page', 'end_page']
    query_cols = ', '.join(columns)
    placeholders = ', '.join(['?'] * len(columns))
    values = [data.get(col) for col in columns]
    query = f"INSERT INTO history ({query_cols}) VALUES ({placeholders})"
    db.execute(query, tuple(values))
    db.commit()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_unique_filename(filename):
    timestamp = int(time.time())
    original_secure_name = secure_filename(filename)
    return f"{timestamp}_{uuid.uuid4().hex[:8]}_{original_secure_name}"

def count_pages(filepath):
    try:
        with open(filepath, 'rb') as f:
            reader = PdfReader(f)
            return len(reader.pages) if reader.pages else 0
    except Exception as e:
        logging.error(f"Erreur lors du comptage des pages pour {filepath}: {e}")
        return 0

def convert_to_pdf(source_path, secure_filename):
    pdf_filename = f"{os.path.splitext(secure_filename)[0]}.pdf"
    pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
    if source_path.lower().endswith('.pdf'):
        shutil.copy(source_path, pdf_path)
        return pdf_path
    lo_command = app.config['LIBREOFFICE_PATH']
    if not lo_command or not os.path.exists(lo_command):
        logging.error(f"Chemin de LibreOffice non configuré ou invalide: {lo_command}")
        return None
    user_profile_path = os.path.join(os.getcwd(), 'lo_profile', str(time.time_ns()))
    os.makedirs(user_profile_path, exist_ok=True)
    user_profile_url = pathlib.Path(user_profile_path).as_uri()
    try:
        command = [lo_command, f'-env:UserInstallation={user_profile_url}', '--headless', '--convert-to', 'pdf:writer_pdf_Export', '--outdir', app.config['CONVERTED_FOLDER'], source_path]
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

def _run_print_job(job):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless"); options.add_argument("--window-size=1920,1080"); options.add_argument('--no-sandbox'); options.add_argument('--disable-dev-shm-usage'); options.add_argument('--ignore-certificate-errors'); options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = None
    try:
        with app.app_context():
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            wait = WebDriverWait(driver, 60)
            for i, task in enumerate(job['tasks']):
                logging.info(f"Impression de la tâche {task['task_id']}...")
                db_update_task(task['task_id'], {'status': STATUS['PRINTING']})
                driver.get(app.config['URL_PDF_PRINT'])
                wait.until(EC.presence_of_element_located((By.XPATH, "//input[contains(@value, \"Démarrer l'impression\")]")))
                Select(driver.find_element(By.CSS_SELECTOR, "select[name='ColorMode']")).select_by_value("0" if task['is_color'] else "1")
                if task['is_duplex']:
                    if not driver.find_element(By.ID, "DuplexMode").is_selected(): driver.find_element(By.ID, "DuplexMode").click()
                    Select(driver.find_element(By.CSS_SELECTOR, "select[name='DuplexType']")).select_by_value("2")
                Select(driver.find_element(By.CSS_SELECTOR, "select[name='MediaSize']")).select_by_value(task.get('paper_size', '2'))
                copies_input = driver.find_element(By.ID, "Copies")
                copies_input.clear(); copies_input.send_keys(str(task.get('copies', 1)))
                if task.get('page_mode') == 'range':
                    range_radio_btn = driver.find_element(By.ID, 'PageMode2')
                    driver.execute_script("arguments[0].click();", range_radio_btn)
                    start_page_input = wait.until(EC.element_to_be_clickable((By.ID, 'StartPage')))
                    end_page_input = wait.until(EC.element_to_be_clickable((By.ID, 'EndPage')))
                    start_page_input.send_keys(str(task.get('start_page', '1'))); end_page_input.send_keys(str(task.get('end_page', '1')))
                else:
                    driver.find_element(By.ID, 'PageMode1').click()
                driver.find_element(By.NAME, "File").send_keys(os.path.abspath(task['path']))
                driver.find_element(By.XPATH, "//input[contains(@value, \"Démarrer l'impression\")]").click()
                wait.until(EC.url_contains("pprint.cgi"))
                return_button_xpath = "//input[contains(@value, 'Retour à la page précédente')]"
                wait.until(EC.element_to_be_clickable((By.XPATH, return_button_xpath)))
                logging.info(f"Tâche {task['task_id']} envoyée à l'imprimante avec succès.")
                db_update_task(task['task_id'], {'status': STATUS['PRINT_SUCCESS']})
                if i < len(job['tasks']) - 1: driver.find_element(By.XPATH, return_button_xpath).click()
        return True
    except Exception as e:
        logging.error(f"ERREUR CRITIQUE DANS SELENIUM: {traceback.format_exc()}")
        if driver: driver.save_screenshot(f"selenium_error_{int(time.time())}.png")
        with app.app_context():
            for task_to_fail in job['tasks']: db_update_task(task_to_fail['task_id'], {'status': STATUS['PRINT_FAILED']})
        return False
    finally:
        if driver: driver.quit()

def _process_single_file_background(task_info):
    with app.app_context():
        task_id = task_info['task_id']; original_filepath = task_info['original_path']; secure_filename = task_info['secure_filename']
        db_update_task(task_id, {'status': STATUS['CONVERTING'], 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        final_pdf_path = convert_to_pdf(original_filepath, secure_filename)
        if not final_pdf_path:
            logging.error(f"Échec de conversion pour {secure_filename}"); db_update_task(task_id, {'status': STATUS['ERROR_CONVERSION']}); return
        db_update_task(task_id, {'status': STATUS['COUNTING']})
        pages = count_pages(final_pdf_path)
        if pages == 0:
            logging.error(f"Échec du comptage de pages pour {final_pdf_path}"); db_update_task(task_id, {'status': STATUS['ERROR_PAGE_COUNT'], 'pages': 0}); return
        db_update_task(task_id, {'pages': pages, 'status': STATUS['READY']})
        logging.info(f"Fichier {secure_filename} prêt pour calcul ({pages} pages).")

@app.route('/')
def index():
    return render_template('index.html', prix_nb=app.config['PRIX_NOIR_BLANC'], prix_c=app.config['PRIX_COULEUR'])

@app.route('/upload_and_process_file', methods=['POST'])
def upload_and_process_file():
    if 'file' not in request.files or not all(f in request.form for f in ['client_name', 'job_id', 'task_id']): return jsonify({'success': False, 'error': "Données manquantes."}), 400
    file = request.files['file']
    if not allowed_file(file.filename): return jsonify({'success': False, 'error': "Type de fichier non autorisé."}), 400
    unique_filename = generate_unique_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(filepath)
    task_data = {'job_id': request.form['job_id'], 'task_id': request.form['task_id'], 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'client_name': request.form['client_name'], 'file_name': file.filename, 'secure_filename': unique_filename, 'status': STATUS['QUEUED']}
    db_insert_task(task_data)
    thread_info = { 'task_id': task_data['task_id'], 'original_path': filepath, 'secure_filename': unique_filename }
    thread = threading.Thread(target=_process_single_file_background, args=(thread_info,)); thread.start()
    return jsonify({'success': True, 'task_id': task_data['task_id']})

@app.route('/get_job_status/<job_id>')
def get_job_status(job_id):
    db = get_db()
    cursor = db.execute("SELECT * FROM history WHERE job_id = ?", (job_id,))
    tasks_from_db = [dict(row) for row in cursor.fetchall()]

    timeout_seconds = app.config.get('TASK_PROCESSING_TIMEOUT', 300)
    now = datetime.now()
    processing_statuses = [STATUS['QUEUED'], STATUS['CONVERTING'], STATUS['COUNTING']]

    for task in tasks_from_db:
        if task['status'] in processing_statuses:
            try:
                task_time = datetime.strptime(task['timestamp'], "%Y-%m-%d %H:%M:%S")
                if now - task_time > timedelta(seconds=timeout_seconds):
                    logging.warning(f"Tâche {task['task_id']} ({task['file_name']}) a dépassé le temps limite. Passage en erreur.")
                    error_status = STATUS['ERROR_CONVERSION']
                    db_update_task(task['task_id'], {'status': error_status})
                    task['status'] = error_status
            except (ValueError, TypeError):
                continue

    tasks_for_ui = [
        {'task_id': t['task_id'], 'file_name': t['file_name'], 'status': t['status'], 'pages': t['pages'], 'price': t['price']}
        for t in tasks_from_db
    ]

    final_statuses = [STATUS['READY'], STATUS['ERROR_CONVERSION'], STATUS['ERROR_PAGE_COUNT'], STATUS['PRINT_FAILED'], STATUS['PRINT_SUCCESS']]
    is_complete = all(task['status'] in final_statuses for task in tasks_from_db)

    return jsonify({'job_id': job_id, 'tasks': tasks_for_ui, 'is_complete': is_complete})

@app.route('/calculate_summary', methods=['POST'])
def calculate_summary():
    data = request.get_json(); job_id = data.get('job_id'); tasks_with_new_options = data.get('tasks')
    if not all([job_id, tasks_with_new_options]): return jsonify({'success': False, 'error': 'Données manquantes.'}), 400
    db = get_db(); cursor = db.execute("SELECT * FROM history WHERE job_id = ? AND status = ?", (job_id, STATUS['READY'])); history_tasks = {dict(row)['task_id']: dict(row) for row in cursor.fetchall()}
    tasks_ready_for_print = []; total_price = 0.0
    for task_options in tasks_with_new_options:
        task_id = task_options.get('task_id'); original_task_data = history_tasks.get(task_id)
        if not original_task_data: continue
        options = task_options.get('options', {}); pages = int(original_task_data.get('pages', 0)); is_color = options.get('color') == 'color'; is_duplex = options.get('siding') == 'recto_verso'; copies = int(options.get('copies', 1)); page_mode = options.get('pagemode', 'all'); start_page = options.get('startpage', '1'); end_page = options.get('endpage', str(pages))
        pages_a_imprimer = pages
        if page_mode == 'range' and start_page.isdigit() and end_page.isdigit():
            try:
                pages_a_imprimer = int(end_page) - int(start_page) + 1
                if pages_a_imprimer < 1: pages_a_imprimer = pages
            except ValueError: pages_a_imprimer = pages
        prix_par_page = app.config['PRIX_COULEUR'] if is_color else app.config['PRIX_NOIR_BLANC']
        prix_tache = pages_a_imprimer * prix_par_page * copies
        total_price += prix_tache
        update_data = {'copies': copies, 'color': 'Couleur' if is_color else 'N&B', 'duplex': 'Recto-Verso' if is_duplex else 'Recto', 'price': f"{prix_tache:.2f}", 'paper_size': options.get('papersize', '2'), 'page_mode': page_mode, 'start_page': start_page, 'end_page': end_page}
        db_update_task(task_id, update_data)
        pdf_filename = f"{os.path.splitext(original_task_data['secure_filename'])[0]}.pdf"
        final_pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
        tasks_ready_for_print.append({'path': final_pdf_path, 'name': original_task_data['file_name'], 'pages': pages, 'copies': copies, 'is_color': is_color, 'is_duplex': is_duplex, 'prix': prix_tache, 'paper_size': options.get('papersize', '2'), 'page_mode': page_mode, 'start_page': start_page, 'end_page': end_page, 'task_id': task_id})
    if not tasks_ready_for_print: return jsonify({'success': False, 'error': 'Aucune tâche valide trouvée.'}), 400
    print_job_summary = {'tasks': tasks_ready_for_print, 'prix_total': total_price, 'client_name': history_tasks[tasks_ready_for_print[0]['task_id']]['client_name'], 'job_id': job_id}
    session['print_job'] = print_job_summary
    return jsonify({'success': True, 'print_job_summary': print_job_summary})

@app.route('/print', methods=['POST'])
def execute_print():
    print_job = session.get('print_job');
    if not print_job: return jsonify({'success': False, 'error': 'Session expirée.'}), 400
    print_thread = threading.Thread(target=_run_print_job, args=(print_job,)); print_thread.start()
    session.pop('print_job', None); return jsonify({'success': True})

def get_task_from_db(task_id):
    cursor = get_db().execute("SELECT * FROM history WHERE task_id = ?", (task_id,)); return cursor.fetchone()

@app.route('/download/<task_id>')
def download_file(task_id):
    if not session.get('is_admin'): return "Accès non autorisé", 403
    task_info = get_task_from_db(task_id)
    if not task_info: return "Tâche introuvable.", 404
    secure_filename = task_info['secure_filename']
    pdf_filename = f"{os.path.splitext(secure_filename)[0]}.pdf"; pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
    if os.path.exists(pdf_path): return send_from_directory(app.config['CONVERTED_FOLDER'], pdf_filename, as_attachment=False)
    original_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename)
    if os.path.exists(original_path): return send_from_directory(app.config['UPLOAD_FOLDER'], secure_filename, as_attachment=True)
    return "Fichier introuvable.", 404

@app.route('/reprint', methods=['POST'])
def reprint_task():
    if not session.get('is_admin'): return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    data = request.get_json(); task_id = data.get('task_id')
    if not task_id: return jsonify({'success': False, 'error': 'task_id manquant.'})
    task_info = get_task_from_db(task_id)
    if not task_info: return jsonify({'success': False, 'error': f'Tâche {task_id} introuvable.'})
    pdf_filename = f"{os.path.splitext(task_info['secure_filename'])[0]}.pdf"; pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
    if not os.path.exists(pdf_path): return jsonify({'success': False, 'error': f'Fichier PDF {pdf_filename} introuvable.'})
    reprint_job = {'tasks': [{'path': pdf_path, 'name': task_info['file_name'], 'copies': 1, 'pages': task_info['pages'], 'is_color': data.get('is_color', False), 'is_duplex': data.get('is_duplex', False), 'paper_size': data.get('paper_size', '2'), 'page_mode': 'all', 'task_id': task_id}]}
    print_thread = threading.Thread(target=_run_print_job, args=(reprint_job,)); print_thread.start(); return jsonify({'success': True})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if (request.form.get('username') == app.config['ADMIN_USERNAME'] and request.form.get('password') == app.config['ADMIN_PASSWORD']):
            session['is_admin'] = True; return jsonify({'success': True})
        else: return jsonify({'success': False, 'error': 'Identifiants incorrects'})
    return render_template('admin.html', is_logged_in=session.get('is_admin', False))

@app.route('/api/admin_data')
def admin_data_api():
    if not session.get('is_admin'): return jsonify({'error': 'Non autorisé'}), 403
    cursor = get_db().execute("SELECT * FROM history ORDER BY timestamp DESC"); history = [dict(row) for row in cursor.fetchall()]
    grouped_commands = OrderedDict()
    for row in history:
        key = row.get('job_id')
        if not key: continue
        if key not in grouped_commands: grouped_commands[key] = {'job_id': key, 'timestamp': row['timestamp'], 'client_name': row['client_name'], 'total_price': 0.0, 'files': [], 'job_status': 'success'}
        grouped_commands[key]['files'].append(row)
        if row.get('price') and 'ERREUR' not in row.get('status', ''):
             try: grouped_commands[key]['total_price'] += float(row.get('price', 0))
             except (ValueError, TypeError): pass
        if 'ERREUR' in row.get('status', ''): grouped_commands[key]['job_status'] = 'error'
        elif 'EN_ATTENTE' in row.get('status', '') and grouped_commands[key]['job_status'] != 'error': grouped_commands[key]['job_status'] = 'pending'
    final_commands = list(grouped_commands.values())
    cursor = get_db().execute("SELECT SUM(price) FROM history WHERE status = ?", (STATUS['PRINT_SUCCESS'],)); total_revenue = cursor.fetchone()[0] or 0.0
    cursor = get_db().execute("SELECT SUM(pages * copies) FROM history WHERE status = ?", (STATUS['PRINT_SUCCESS'],)); total_pages_printed = cursor.fetchone()[0] or 0
    return jsonify({'commands': final_commands, 'total_revenue': f"{total_revenue:.2f}", 'total_pages': total_pages_printed})

@app.route('/api/delete_task/<task_id>', methods=['POST'])
def delete_task(task_id):
    if not session.get('is_admin'): return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    db = get_db(); db.execute("DELETE FROM history WHERE task_id = ?", (task_id,)); db.commit(); return jsonify({'success': True})

@app.route('/api/delete_all_tasks', methods=['POST'])
def delete_all_tasks():
    if not session.get('is_admin'): return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    db = get_db(); db.execute("DELETE FROM history"); db.commit(); logging.warning("L'historique complet a été supprimé par un admin."); return jsonify({'success': True})

@app.route('/logout')
def logout():
    session.pop('is_admin', None); return redirect(url_for('login'))

@app.cli.command('init-db')
def init_db_command():
    """Crée les tables de la base de données."""
    with app.app_context():
        init_db()
    click.echo('Base de données initialisée.')

def create_folders():
    for folder in [app.config['UPLOAD_FOLDER'], app.config['CONVERTED_FOLDER']]:
        if not os.path.exists(folder): os.makedirs(folder); logging.info(f"Dossier créé : {folder}")

if __name__ == '__main__':
    create_folders()
    app.run(host='0.0.0.0', port=5001)
