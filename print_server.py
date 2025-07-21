# print_server.py
import os
import time
import sys
import shutil
import glob
import sqlite3
from datetime import datetime, timedelta
from collections import OrderedDict
import threading
import uuid
import logging
import traceback
from multiprocessing import Process

import click
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from werkzeug.utils import secure_filename

from config import Config
from core import (
    db_insert_task, db_update_task, process_single_file_background,
    get_db_connection as core_get_db_connection,
    ALLOWED_EXTENSIONS, STATUS
)
from email_processor import check_emails_periodically

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
app.config.from_object(Config)

@app.context_processor
def inject_cache_buster():
    return dict(cache_buster=int(time.time()))

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

def get_db_connection():
    return core_get_db_connection(app.config['DATABASE_FILE'])

def init_db():
    with get_db_connection() as conn:
        with app.open_resource('schema.sql', mode='r') as f:
            conn.cursor().executescript(f.read())
        conn.commit()
    logging.info("Base de données initialisée avec le schéma.")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_unique_filename(filename):
    timestamp = int(time.time())
    original_secure_name = secure_filename(filename)
    return f"{timestamp}_{uuid.uuid4().hex[:8]}_{original_secure_name}"

def _run_print_job(job):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless"); options.add_argument("--window-size=1920,1080"); options.add_argument('--no-sandbox'); options.add_argument('--disable-dev-shm-usage'); options.add_argument('--ignore-certificate-errors'); options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 60)
        for i, task in enumerate(job['tasks']):
            logging.info(f"Impression de la tâche {task['task_id']}...")
            db_update_task(app.config['DATABASE_FILE'], task['task_id'], {'status': STATUS['PRINTING']})
            driver.get(app.config['URL_PDF_PRINT'])
            wait.until(EC.presence_of_element_located((By.XPATH, app.config['PRINTER_START_BUTTON_XPATH'])))
            Select(driver.find_element(By.CSS_SELECTOR, app.config['PRINTER_COLOR_MODE_SELECTOR'])).select_by_value("0" if task['is_color'] else "1")
            if task['is_duplex']:
                if not driver.find_element(By.ID, app.config['PRINTER_DUPLEX_CHECKBOX_ID']).is_selected(): driver.find_element(By.ID, app.config['PRINTER_DUPLEX_CHECKBOX_ID']).click()
                Select(driver.find_element(By.CSS_SELECTOR, app.config['PRINTER_DUPLEX_TYPE_SELECTOR'])).select_by_value("2")
            Select(driver.find_element(By.CSS_SELECTOR, app.config['PRINTER_MEDIA_SIZE_SELECTOR'])).select_by_value(task.get('paper_size', '2'))
            copies_input = driver.find_element(By.ID, app.config['PRINTER_COPIES_INPUT_ID'])
            copies_input.clear(); copies_input.send_keys(str(task.get('copies', 1)))
            if task.get('page_mode') == 'range' and task.get('start_page') and task.get('end_page'):
                range_radio_btn = driver.find_element(By.ID, app.config['PRINTER_PAGE_MODE_RANGE_ID'])
                driver.execute_script("arguments[0].click();", range_radio_btn)
                start_page_input = wait.until(EC.element_to_be_clickable((By.ID, app.config['PRINTER_START_PAGE_INPUT_ID'])))
                end_page_input = wait.until(EC.element_to_be_clickable((By.ID, app.config['PRINTER_END_PAGE_INPUT_ID'])))
                start_page_input.send_keys(str(task.get('start_page', '1'))); end_page_input.send_keys(str(task.get('end_page', '1')))
            else:
                driver.find_element(By.ID, app.config['PRINTER_PAGE_MODE_ALL_ID']).click()
            driver.find_element(By.NAME, app.config['PRINTER_FILE_INPUT_NAME']).send_keys(os.path.abspath(task['path']))
            driver.find_element(By.XPATH, app.config['PRINTER_START_BUTTON_XPATH']).click()
            wait.until(EC.url_contains(app.config['PRINTER_SUCCESS_URL_CONTAINS']))
            return_button_xpath = app.config['PRINTER_RETURN_BUTTON_XPATH']
            wait.until(EC.element_to_be_clickable((By.XPATH, return_button_xpath)))
            logging.info(f"Tâche {task['task_id']} envoyée à l'imprimante avec succès.")
            final_success_status = STATUS['PRINT_SUCCESS_NO_COUNT'] if task.get('pages', 0) == 0 else STATUS['PRINT_SUCCESS']
            db_update_task(app.config['DATABASE_FILE'], task['task_id'], {'status': final_success_status})
            if i < len(job['tasks']) - 1: driver.find_element(By.XPATH, return_button_xpath).click()
        return True
    except Exception as e:
        logging.error(f"ERREUR CRITIQUE DANS SELENIUM: {traceback.format_exc()}")
        if driver: driver.save_screenshot(f"selenium_error_{int(time.time())}.png")
        for task_to_fail in job['tasks']:
            db_update_task(app.config['DATABASE_FILE'], task_to_fail['task_id'], {'status': STATUS['PRINT_FAILED']})
        return False
    finally:
        if driver: driver.quit()

@app.route('/')
def index():
    username = session.get('username')
    return render_template('index.html', prix_nb=app.config['PRIX_NOIR_BLANC'], prix_c=app.config['PRIX_COULEUR'], username=username)

@app.route('/upload_and_process_file', methods=['POST'])
def upload_and_process_file():
    username = session.get('username')
    if not username:
        return jsonify({'success': False, 'error': "Session expirée, veuillez vous reconnecter."}), 401

    if 'file' not in request.files or not all(f in request.form for f in ['job_id', 'task_id']):
        return jsonify({'success': False, 'error': "Données manquantes."}), 400

    file = request.files['file']
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': "Type de fichier non autorisé."}), 400

    unique_filename = generate_unique_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(filepath)

    try:
        if os.path.getsize(filepath) == 0:
            task_data = {'job_id': request.form['job_id'], 'task_id': request.form['task_id'], 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'username': username, 'file_name': file.filename, 'secure_filename': unique_filename, 'status': STATUS['ERROR_FILE_EMPTY'], 'source': 'upload', 'original_path': filepath}
            db_insert_task(app.config['DATABASE_FILE'], task_data)
            os.remove(filepath)
            return jsonify({'success': True, 'task_id': task_data['task_id']})
    except OSError as e:
        return jsonify({'success': False, 'error': "Erreur serveur à la lecture du fichier."}), 500

    task_data = {'job_id': request.form['job_id'], 'task_id': request.form['task_id'], 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'username': username, 'file_name': file.filename, 'secure_filename': unique_filename, 'status': STATUS['QUEUED'], 'source': 'upload', 'original_path': filepath}
    db_insert_task(app.config['DATABASE_FILE'], task_data)

    thread_args = {'task_id': task_data['task_id'], 'original_path': filepath, 'secure_filename': unique_filename}
    thread = threading.Thread(target=process_single_file_background, args=(thread_args, app.config)); thread.start()
    return jsonify({'success': True, 'task_id': task_data['task_id']})

@app.route('/get_job_status/<job_id>')
def get_job_status(job_id):
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM history WHERE job_id = ?", (job_id,))
        tasks_from_db = [dict(row) for row in cursor.fetchall()]
    timeout_seconds = app.config.get('TASK_PROCESSING_TIMEOUT', 30)
    now = datetime.now()
    processing_statuses = [STATUS['QUEUED'], STATUS['CONVERTING'], STATUS['COUNTING']]
    for task in tasks_from_db:
        if task['status'] in processing_statuses:
            try:
                task_time = datetime.strptime(task['timestamp'], "%Y-%m-%d %H:%M:%S")
                if now - task_time > timedelta(seconds=timeout_seconds):
                    error_status = STATUS['ERROR_CONVERSION']
                    db_update_task(app.config['DATABASE_FILE'], task['task_id'], {'status': error_status})
                    task['status'] = error_status
            except (ValueError, TypeError): continue
    tasks_for_ui = [{'task_id': t['task_id'], 'file_name': t['file_name'], 'status': t['status'], 'pages': t['pages'], 'price': t['price']} for t in tasks_from_db]
    final_statuses = [STATUS['READY'], STATUS['READY_NO_PAGE_COUNT'], STATUS['ERROR_CONVERSION'], STATUS['ERROR_PAGE_COUNT'], STATUS['ERROR_FILE_EMPTY'], STATUS['ERROR_FATAL_READ'], STATUS['PRINT_FAILED'], STATUS['PRINT_SUCCESS'], STATUS['PRINT_SUCCESS_NO_COUNT']]
    is_complete = all(task['status'] in final_statuses for task in tasks_from_db)
    return jsonify({'job_id': job_id, 'tasks': tasks_for_ui, 'is_complete': is_complete})

@app.route('/calculate_summary', methods=['POST'])
def calculate_summary():
    username = session.get('username')
    if not username: return jsonify({'success': False, 'error': 'Session expirée.'}), 401
    data = request.get_json(); job_id = data.get('job_id'); tasks_with_new_options = data.get('tasks')
    if not all([job_id, tasks_with_new_options]): return jsonify({'success': False, 'error': 'Données manquantes.'}), 400
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM history WHERE job_id = ? AND (status = ? OR status = ?)", (job_id, STATUS['READY'], STATUS['READY_NO_PAGE_COUNT']));
        history_tasks = {dict(row)['task_id']: dict(row) for row in cursor.fetchall()}
    tasks_ready_for_print = []; total_price = 0.0
    for task_options in tasks_with_new_options:
        task_id = task_options.get('task_id'); original_task_data = history_tasks.get(task_id)
        if not original_task_data: continue
        options = task_options.get('options', {});
        pages = int(original_task_data.get('pages') or 0);
        is_color = options.get('color') == 'color'; is_duplex = options.get('siding') == 'recto_verso'; copies = int(options.get('copies', 1)); page_mode = options.get('pagemode', 'all'); start_page = options.get('startpage'); end_page = options.get('endpage')
        prix_tache = 0.0
        pages_a_imprimer = 0
        if pages > 0:
            pages_a_imprimer = pages
            if page_mode == 'range' and start_page and end_page and start_page.isdigit() and end_page.isdigit():
                try:
                    pages_a_imprimer = int(end_page) - int(start_page) + 1
                    if pages_a_imprimer < 1: pages_a_imprimer = pages
                except ValueError: pages_a_imprimer = pages
            prix_par_page = app.config['PRIX_COULEUR'] if is_color else app.config['PRIX_NOIR_BLANC']
            prix_tache = pages_a_imprimer * prix_par_page * copies
            total_price += prix_tache
        if pages == 0:
            page_mode = 'all'; start_page = None; end_page = None
        update_data = {'copies': copies, 'color': 'Couleur' if is_color else 'N&B', 'duplex': 'Recto-Verso' if is_duplex else 'Recto', 'price': f"{prix_tache:.2f}" if pages > 0 else "0.00", 'paper_size': options.get('papersize', '2'), 'page_mode': page_mode, 'start_page': start_page, 'end_page': end_page}
        db_update_task(app.config['DATABASE_FILE'], task_id, update_data)
        pdf_filename = f"{os.path.splitext(original_task_data['secure_filename'])[0]}.pdf"
        final_pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
        tasks_ready_for_print.append({'path': final_pdf_path, 'name': original_task_data['file_name'], 'pages': pages, 'copies': copies, 'is_color': is_color, 'is_duplex': is_duplex, 'prix': prix_tache, 'paper_size': options.get('papersize', '2'), 'page_mode': page_mode, 'start_page': start_page, 'end_page': end_page, 'task_id': task_id})
    if not tasks_ready_for_print: return jsonify({'success': False, 'error': 'Aucune tâche valide trouvée.'}), 400
    print_job_summary = {'tasks': tasks_ready_for_print, 'prix_total': total_price, 'username': username, 'job_id': job_id}
    session['print_job'] = print_job_summary
    return jsonify({'success': True, 'print_job_summary': print_job_summary})

@app.route('/print', methods=['POST'])
def execute_print():
    print_job = session.get('print_job');
    if not print_job: return jsonify({'success': False, 'error': 'Session expirée.'}), 400
    print_process = Process(target=_run_print_job, args=(print_job,));
    print_process.start()
    session.pop('print_job', None);
    return jsonify({'success': True})

# MODIFIÉ : La fonction retourne maintenant un dictionnaire ou None
def get_task_from_db(task_id):
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM history WHERE task_id = ?", (task_id,));
        row = cursor.fetchone()
        return dict(row) if row else None

@app.route('/preview/<task_id>')
def preview_file(task_id):
    task_info = get_task_from_db(task_id)
    if not task_info: return "Tâche introuvable.", 404
    secure_filename_val = task_info['secure_filename']
    pdf_filename = f"{os.path.splitext(secure_filename_val)[0]}.pdf"
    pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
    if os.path.exists(pdf_path):
        return send_from_directory(app.config['CONVERTED_FOLDER'], pdf_filename, as_attachment=False)
    return "Le fichier de prévisualisation n'est pas encore prêt ou a été supprimé.", 404

@app.route('/download/<task_id>')
def download_file(task_id):
    force_download = request.args.get('dl') == '1'
    task_info = get_task_from_db(task_id)
    if not task_info:
        return "Tâche introuvable. Elle a peut-être été supprimée.", 404
    secure_filename_val = task_info['secure_filename']
    pdf_filename = f"{os.path.splitext(secure_filename_val)[0]}.pdf"
    pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
    if os.path.exists(pdf_path):
        return send_from_directory(app.config['CONVERTED_FOLDER'], pdf_filename, as_attachment=force_download)
    original_path = task_info.get('original_path')
    if original_path and os.path.exists(original_path):
        directory, filename = os.path.split(original_path)
        return send_from_directory(directory, filename, as_attachment=force_download)
    return "Fichier introuvable sur le serveur.", 404

@app.route('/reprint', methods=['POST'])
def reprint_task():
    if not session.get('is_admin'): return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    data = request.get_json()
    task_id = data.get('task_id')
    if not task_id: return jsonify({'success': False, 'error': 'task_id manquant.'}), 400
    task_info = get_task_from_db(task_id)
    if not task_info: return jsonify({'success': False, 'error': f'Tâche {task_id} introuvable.'}), 404
    pdf_filename = f"{os.path.splitext(task_info['secure_filename'])[0]}.pdf"
    pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
    if not os.path.exists(pdf_path): return jsonify({'success': False, 'error': f'Fichier PDF {pdf_filename} introuvable.'}), 404
    reprint_job = {'tasks': [{'path': pdf_path, 'name': task_info['file_name'], 'copies': data.get('copies', 1), 'pages': task_info['pages'], 'is_color': data.get('is_color', False), 'is_duplex': data.get('is_duplex', False), 'paper_size': task_info['paper_size'] or '2', 'page_mode': 'all', 'task_id': task_id}]}
    reprint_process = Process(target=_run_print_job, args=(reprint_job,))
    reprint_process.start()
    return jsonify({'success': True})

@app.route('/api/reprint_job', methods=['POST'])
def reprint_job():
    if not session.get('is_admin'): return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    data = request.get_json()
    job_id = data.get('job_id')
    options = data.get('options', {})
    if not job_id: return jsonify({'success': False, 'error': 'job_id manquant.'}), 400
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM history WHERE job_id = ?", (job_id,))
        all_tasks_in_job = cursor.fetchall()
    if not all_tasks_in_job: return jsonify({'success': False, 'error': f'Job {job_id} introuvable.'}), 404
    tasks_for_reprint = []
    unprintable_statuses = ['ERREUR_CONVERSION', 'ERREUR_FICHIER_VIDE', 'ERREUR_LECTURE_FATALE']
    for task_info_row in all_tasks_in_job:
        task_info = dict(task_info_row) # On s'assure de travailler avec un dictionnaire
        if task_info['status'] in unprintable_statuses: continue
        pdf_filename = f"{os.path.splitext(task_info['secure_filename'])[0]}.pdf"
        pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
        if os.path.exists(pdf_path):
            tasks_for_reprint.append({'path': pdf_path, 'name': task_info['file_name'], 'copies': options.get('copies', 1), 'pages': task_info['pages'], 'is_color': options.get('is_color', False), 'is_duplex': options.get('is_duplex', False), 'paper_size': task_info['paper_size'] or '2', 'page_mode': 'all', 'task_id': task_info['task_id']})
    if not tasks_for_reprint: return jsonify({'success': False, 'error': 'Aucun fichier imprimable trouvé dans cette commande.'})
    reprint_job_data = {'tasks': tasks_for_reprint}
    reprint_process = Process(target=_run_print_job, args=(reprint_job_data,))
    reprint_process.start()
    return jsonify({'success': True})

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
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM history ORDER BY timestamp DESC");
        history = [dict(row) for row in cursor.fetchall()]
    grouped_commands = OrderedDict()
    for row in history:
        key = row.get('job_id')
        if not key: continue
        if key not in grouped_commands:
            grouped_commands[key] = {'job_id': key, 'timestamp': row['timestamp'], 'username': row['username'], 'total_price': 0.0, 'files': [], 'source': row.get('source', 'upload'), 'email_subject': row.get('email_subject')}
        grouped_commands[key]['files'].append(row)
        try:
            price = float(row.get('price') or 0.0)
            if 'ERREUR' not in row.get('status', ''):
                grouped_commands[key]['total_price'] += price
        except (ValueError, TypeError): pass
    for job_id, command in grouped_commands.items():
        statuses = [f['status'] for f in command['files']]
        job_status = 'unknown'
        if any('ERREUR' in s for s in statuses): job_status = 'error'
        elif all(s in (STATUS['PRINT_SUCCESS'], STATUS['PRINT_SUCCESS_NO_COUNT']) for s in statuses): job_status = 'completed'
        elif any(s == STATUS['PRINTING'] for s in statuses): job_status = 'printing'
        elif any(s in (STATUS['QUEUED'], STATUS['CONVERTING'], STATUS['COUNTING']) for s in statuses): job_status = 'pending'
        elif all(s in (STATUS['READY'], STATUS['READY_NO_PAGE_COUNT']) for s in statuses): job_status = 'ready'
        else: job_status = 'pending'
        command['job_status'] = job_status
    upload_commands = [cmd for cmd in grouped_commands.values() if cmd['source'] == 'upload']
    email_commands = [cmd for cmd in grouped_commands.values() if cmd['source'] == 'email']
    with get_db_connection() as conn:
        valid_print_statuses = (STATUS['PRINT_SUCCESS'], STATUS['PRINT_SUCCESS_NO_COUNT'])
        placeholders = ','.join('?' for _ in valid_print_statuses)
        cursor = conn.execute(f"SELECT SUM(price) FROM history WHERE status IN ({placeholders})", valid_print_statuses);
        total_revenue = cursor.fetchone()[0] or 0.0
        cursor = conn.execute(f"SELECT SUM(pages * copies) FROM history WHERE status IN ({placeholders}) AND pages > 0", valid_print_statuses);
        total_pages_printed = cursor.fetchone()[0] or 0
    return jsonify({'upload_commands': upload_commands, 'email_commands': email_commands, 'total_revenue': f"{total_revenue:.2f}", 'total_pages': total_pages_printed})

@app.route('/api/delete_task/<task_id>', methods=['POST'])
def delete_task(task_id):
    if not session.get('is_admin'): return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    with get_db_connection() as conn:
        conn.execute("DELETE FROM history WHERE task_id = ?", (task_id,));
        conn.commit();
    return jsonify({'success': True})

@app.route('/api/delete_all_tasks', methods=['POST'])
def delete_all_tasks():
    if not session.get('is_admin'): return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    with get_db_connection() as conn:
        conn.execute("DELETE FROM history");
        conn.commit();
    logging.warning("L'historique complet a été supprimé par un admin.");
    return jsonify({'success': True})

@app.route('/api/browse_files')
def browse_files():
    if not session.get('is_admin'): return jsonify({'error': 'Non autorisé'}), 403
    base_path = app.config['UPLOAD_FOLDER']
    files_list = []
    for root, dirs, files in os.walk(base_path):
        for name in files:
            file_path = os.path.join(root, name)
            try:
                stat = os.stat(file_path)
                files_list.append({'name': name, 'path': os.path.relpath(file_path, base_path), 'size': stat.st_size, 'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M')})
            except OSError: continue
    files_list.sort(key=lambda x: x['modified'], reverse=True)
    return jsonify(files_list)

@app.route('/api/download_raw_file')
def download_raw_file():
    if not session.get('is_admin'): return "Accès non autorisé", 403
    file_rel_path = request.args.get('path')
    if not file_rel_path: return "Chemin de fichier manquant.", 400
    force_download = request.args.get('dl') == '1'
    base_dir = os.path.abspath(app.config['UPLOAD_FOLDER'])
    requested_path = os.path.abspath(os.path.join(base_dir, file_rel_path))
    if not requested_path.startswith(base_dir):
        return "Chemin invalide.", 400
    if os.path.exists(requested_path) and os.path.isfile(requested_path):
        directory, filename = os.path.split(requested_path)
        return send_from_directory(directory, filename, as_attachment=force_download)
    return "Fichier introuvable.", 404

@app.route('/user_login', methods=['POST'])
def user_login():
    username = request.form.get('username')
    if not username or len(username) < 3:
        return jsonify({'success': False, 'error': 'L\'identifiant doit faire au moins 3 caractères.'})

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        if not user:
            try:
                cursor.execute("INSERT INTO users (username) VALUES (?)", (username,))
                conn.commit()
                logging.info(f"Nouvel utilisateur créé : {username}")
            except sqlite3.IntegrityError:
                 return jsonify({'success': False, 'error': 'Cet identifiant est déjà utilisé.'})

    session['username'] = username
    logging.info(f"Utilisateur connecté : {username}")
    return jsonify({'success': True})

@app.route('/user_logout')
def user_logout():
    session.pop('username', None)
    return redirect(url_for('index'))

@app.route('/api/user_history')
def user_history_api():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Non autorisé'}), 401

    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM history WHERE username = ? ORDER BY timestamp DESC", (username,));
        history = [dict(row) for row in cursor.fetchall()]

    grouped_commands = OrderedDict()
    for row in history:
        key = row.get('job_id')
        if not key: continue
        if key not in grouped_commands:
            grouped_commands[key] = {'job_id': key, 'timestamp': row['timestamp'], 'username': row['username'], 'total_price': 0.0, 'files': [], 'source': row.get('source', 'upload'), 'email_subject': row.get('email_subject')}
        grouped_commands[key]['files'].append(row)
        try:
            price = float(row.get('price') or 0.0)
            if 'ERREUR' not in row.get('status', ''):
                grouped_commands[key]['total_price'] += price
        except (ValueError, TypeError): pass

    return jsonify(list(grouped_commands.values()))

@app.route('/api/user_reprint', methods=['POST'])
def user_reprint_task():
    username = session.get('username')
    if not username:
        return jsonify({'success': False, 'error': 'Session expirée, veuillez vous reconnecter.'}), 401

    data = request.get_json()
    task_id = data.get('task_id')
    if not task_id:
        return jsonify({'success': False, 'error': 'Données de la tâche manquantes.'}), 400

    task_info = get_task_from_db(task_id)
    if not task_info:
        return jsonify({'success': False, 'error': f'Tâche {task_id} introuvable.'}), 404

    # Contrôle de sécurité : l'utilisateur ne peut réimprimer que ses propres tâches
    if task_info['username'] != username:
        return jsonify({'success': False, 'error': 'Action non autorisée.'}), 403

    pdf_filename = f"{os.path.splitext(task_info['secure_filename'])[0]}.pdf"
    pdf_path = os.path.join(app.config['CONVERTED_FOLDER'], pdf_filename)
    if not os.path.exists(pdf_path):
        return jsonify({'success': False, 'error': f'Le fichier à imprimer n\'est plus disponible sur le serveur.'}), 404

    reprint_job = {
        'tasks': [{
            'path': pdf_path,
            'name': task_info['file_name'],
            'copies': data.get('copies', 1),
            'pages': task_info['pages'],
            'is_color': data.get('is_color', False),
            'is_duplex': data.get('is_duplex', False),
            # MODIFIÉ : Utilisation de .get() car task_info est maintenant un dictionnaire
            'paper_size': task_info.get('paper_size') or '2',
            'page_mode': 'all', # La réimpression depuis l'historique imprime toujours tout le document
            'task_id': task_id
        }]
    }

    reprint_process = Process(target=_run_print_job, args=(reprint_job,))
    reprint_process.start()
    return jsonify({'success': True})

@app.route('/logout')
def logout():
    session.pop('is_admin', None); return redirect(url_for('login'))

@app.cli.command('init-db')
def init_db_command():
    init_db()
    click.echo('Base de données initialisée.')

def create_folders():
    for folder in [app.config['UPLOAD_FOLDER'], app.config['CONVERTED_FOLDER'], app.config['EMAIL_FOLDER']]:
        if not os.path.exists(folder): os.makedirs(folder); logging.info(f"Dossier créé : {folder}")

def cleanup_old_files_periodically():
    logging.info("Lancement du thread de nettoyage périodique...")
    while True:
        time.sleep(86400)
        with app.app_context():
            logging.info("Exécution du nettoyage des anciens fichiers...")
            folders_to_clean = [app.config['UPLOAD_FOLDER'], app.config['CONVERTED_FOLDER'], app.config['EMAIL_FOLDER']]
            retention_days = app.config.get('FILE_RETENTION_DAYS', 7)
            for folder in folders_to_clean:
                if not os.path.isdir(folder): continue
                files = glob.glob(os.path.join(folder, '*'))
                for file_path in files:
                    if not os.path.isfile(file_path): continue
                    try:
                        file_mod_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                        if datetime.now() - file_mod_time > timedelta(days=retention_days):
                            os.remove(file_path)
                            logging.info(f"Fichier supprimé (car plus ancien que {retention_days} jours) : {file_path}")
                    except Exception as e:
                        logging.error(f"Erreur lors de la suppression de {file_path}: {e}")

if __name__ == '__main__':
    if sys.platform.startswith('win') or sys.platform.startswith('darwin'):
        from multiprocessing import freeze_support
        freeze_support()
    create_folders()
    email_thread = threading.Thread(target=check_emails_periodically, args=(app.config, app.app_context), daemon=True)
    email_thread.start()
    cleanup_thread = threading.Thread(target=cleanup_old_files_periodically, daemon=True)
    cleanup_thread.start()
    app.run(host='0.0.0.0', port=5001)
