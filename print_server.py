import os
import time
import sys
import csv
import subprocess
import shutil
from datetime import datetime
import pathlib
from collections import OrderedDict
import threading
import uuid

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from PyPDF2 import PdfReader
from werkzeug.utils import secure_filename

# --- Configuration ---
PRINTER_IP = "192.168.1.18:8000"
PRIX_NOIR_BLANC = 0.20
PRIX_COULEUR = 0.70
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "4187"
URL_PDF_PRINT = f"http://{PRINTER_IP}/direct"

app = Flask(__name__)
app.secret_key = 'session_impression_finale_2025_admin'

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
CONVERTED_FOLDER = os.path.join(UPLOAD_FOLDER, 'converted')
HISTORY_FILE = os.path.join(os.getcwd(), 'history.csv')

# --- Statuts pour la gestion des tâches ---
STATUS = {
    'UPLOADING': 'TELECHARGEMENT_EN_COURS',
    'QUEUED': 'EN_ATTENTE_TRAITEMENT',
    'CONVERTING': 'CONVERSION_EN_COURS',
    'COUNTING': 'COMPTAGE_PAGES',
    'ERROR_CONVERSION': 'ERREUR_CONVERSION',
    'ERROR_PAGE_COUNT': 'ERREUR_COMPTAGE_PAGES',
    'READY': 'PRET_POUR_CALCUL',
    'PRINTING': 'IMPRESSION_EN_COURS',
    'PRINT_SUCCESS': 'IMPRIME_AVEC_SUCCES',
    'PRINT_FAILED': 'ERREUR_IMPRESSION'
}
history_lock = threading.Lock()

for folder in [UPLOAD_FOLDER, CONVERTED_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods'}

# --- Fonctions utilitaires ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_unique_filename(filename):
    timestamp = int(time.time())
    original_secure_name = secure_filename(filename)
    unique_name = f"{timestamp}_{uuid.uuid4().hex[:8]}_{original_secure_name}"
    return unique_name

def count_pages(filepath):
    try:
        with open(filepath, 'rb') as f:
            reader = PdfReader(f)
            return len(reader.pages) if reader.pages else 0
    except Exception:
        return 0

def update_history(task_data):
    with history_lock:
        fieldnames = ['job_id', 'task_id', 'timestamp', 'client_name', 'file_name', 'secure_filename', 'pages', 'copies', 'color', 'duplex', 'price', 'status', 'paper_size', 'page_mode', 'start_page', 'end_page']
        rows = []
        if not os.path.isfile(HISTORY_FILE) or os.path.getsize(HISTORY_FILE) == 0:
            with open(HISTORY_FILE, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()

        try:
            with open(HISTORY_FILE, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                if reader.fieldnames: rows = list(reader)
        except (csv.Error, Exception) as e:
            print(f"AVERTISSEMENT : Impossible de lire history.csv. Erreur: {e}")
            rows = []

        updated = False
        for row in rows:
            if row.get('task_id') == task_data.get('task_id'):
                row.update(task_data)
                updated = True
                break

        if not updated:
            new_row = {key: task_data.get(key, '') for key in fieldnames}
            rows.append(new_row)

        temp_file = HISTORY_FILE + '.tmp'
        try:
            with open(temp_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            shutil.move(temp_file, HISTORY_FILE)
        except Exception as e:
            print(f"ERREUR CRITIQUE lors de l'écriture de l'historique : {e}")

def convert_to_pdf(source_path, secure_filename):
    pdf_filename = f"{os.path.splitext(secure_filename)[0]}.pdf"
    pdf_path = os.path.join(CONVERTED_FOLDER, pdf_filename)

    if source_path.lower().endswith('.pdf'):
        shutil.copy(source_path, pdf_path)
        return pdf_path

    lo_command = "C:\\Program Files\\LibreOffice\\program\\soffice.exe"
    if not os.path.exists(lo_command): return None
    user_profile_path = os.path.join(os.getcwd(), 'lo_profile', str(time.time_ns()))
    os.makedirs(user_profile_path, exist_ok=True)
    user_profile_url = pathlib.Path(user_profile_path).as_uri()
    try:
        command = [lo_command, f'-env:UserInstallation={user_profile_url}', '--headless', '--convert-to', 'pdf:writer_pdf_Export', '--outdir', CONVERTED_FOLDER, source_path]
        subprocess.run(command, check=True, timeout=120)
        timeout = 20; start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                time.sleep(1)
                shutil.rmtree(user_profile_path, ignore_errors=True)
                return pdf_path
            time.sleep(0.5)
        shutil.rmtree(user_profile_path, ignore_errors=True)
        return None
    except Exception as e:
        print(f"Erreur de conversion LibreOffice : {e}")
        shutil.rmtree(user_profile_path, ignore_errors=True)
        return None

def _run_print_job(job):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless"); options.add_argument("--window-size=1920,1080")
    options.add_argument('--no-sandbox'); options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--ignore-certificate-errors'); options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 60)
        num_tasks = len(job['tasks'])
        for i, task in enumerate(job['tasks']):
            update_data = {'task_id': task['task_id'], 'status': STATUS['PRINTING']}
            update_history(update_data)

            driver.get(URL_PDF_PRINT)
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
                start_page_input.send_keys(str(task.get('start_page', '1')))
                end_page_input.send_keys(str(task.get('end_page', '1')))
            else:
                driver.find_element(By.ID, 'PageMode1').click()

            driver.find_element(By.NAME, "File").send_keys(os.path.abspath(task['path']))
            driver.find_element(By.XPATH, "//input[contains(@value, \"Démarrer l'impression\")]").click()
            wait.until(EC.url_contains("pprint.cgi"))
            return_button_xpath = "//input[contains(@value, 'Retour à la page précédente')]"
            wait.until(EC.element_to_be_clickable((By.XPATH, return_button_xpath)))

            update_data_success = {'task_id': task['task_id'], 'status': STATUS['PRINT_SUCCESS']}
            update_history(update_data_success)

            if i < num_tasks - 1:
                driver.find_element(By.XPATH, return_button_xpath).click()
        return True
    except Exception as e:
        import traceback; traceback.print_exc()
        if driver: driver.save_screenshot(f"selenium_error_{int(time.time())}.png")
        for task_to_fail in job['tasks']:
             update_history({'task_id': task_to_fail['task_id'], 'status': STATUS['PRINT_FAILED']})
        return False
    finally:
        if driver: driver.quit()

def _process_single_file_background(task_info):
    job_id = task_info['job_id']
    task_id = task_info['task_id']
    original_filepath = task_info['original_path']
    secure_filename = task_info['secure_filename']
    form_data = task_info['form_data']
    client_name = task_info['client_name']

    task_data_base = {
        'job_id': job_id, 'task_id': task_id, 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'client_name': client_name, 'file_name': task_info['original_filename'],
        'secure_filename': secure_filename
    }

    update_history({**task_data_base, 'status': STATUS['CONVERTING']})
    final_pdf_path = convert_to_pdf(original_filepath, secure_filename)
    if not final_pdf_path:
        update_history({**task_data_base, 'status': STATUS['ERROR_CONVERSION']}); return

    update_history({**task_data_base, 'status': STATUS['COUNTING']})
    pages = count_pages(final_pdf_path)
    if pages == 0:
        update_history({**task_data_base, 'status': STATUS['ERROR_PAGE_COUNT'], 'pages': 0}); return

    prix_par_page = PRIX_COULEUR if form_data.get('color') == 'color' else PRIX_NOIR_BLANC
    prix_tache = pages * prix_par_page * int(form_data.get('copies', 1))

    full_task_info = {
        **task_data_base, 'pages': pages, 'price': f"{prix_tache:.2f}",
        'status': STATUS['READY']
    }
    update_history(full_task_info)

# --- Routes Flask ---
@app.route('/')
def index():
    success_message = request.args.get('success_message')
    error_message = request.args.get('error_message')
    return render_template('index.html',
                           prix_nb=PRIX_NOIR_BLANC,
                           prix_c=PRIX_COULEUR,
                           success_message=success_message,
                           error_message=error_message)

@app.route('/upload_and_process_file', methods=['POST'])
def upload_and_process_file():
    client_name = request.form.get('client_name')
    job_id = request.form.get('job_id')
    task_id = request.form.get('task_id')
    file = request.files.get('file')

    if not all([client_name, job_id, task_id, file]):
        return jsonify({'success': False, 'error': "Données manquantes."}), 400
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': "Type de fichier non autorisé."}), 400

    unique_filename = generate_unique_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
    file.save(filepath)

    initial_task_data = {
        'job_id': job_id, 'task_id': task_id, 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'client_name': client_name, 'file_name': file.filename, 'secure_filename': unique_filename,
        'status': STATUS['QUEUED']
    }
    update_history(initial_task_data)

    task_info = {
        'job_id': job_id, 'task_id': task_id, 'original_path': filepath,
        'secure_filename': unique_filename, 'original_filename': file.filename,
        'client_name': client_name, 'form_data': {key: val for key, val in request.form.items()}
    }

    thread = threading.Thread(target=_process_single_file_background, args=(task_info,))
    thread.start()
    return jsonify({'success': True, 'job_id': job_id, 'task_id': task_id})

@app.route('/get_job_status/<job_id>')
def get_job_status(job_id):
    all_tasks_from_history = []
    if os.path.exists(HISTORY_FILE):
        with history_lock:
            with open(HISTORY_FILE, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                all_tasks_from_history = [row for row in reader if row.get('job_id') == job_id]

    if not all_tasks_from_history:
        return jsonify({'tasks': [], 'is_complete': True})

    job_is_complete = True
    tasks_for_ui = []

    for task in all_tasks_from_history:
        status = task.get('status', '')
        tasks_for_ui.append({
            'task_id': task.get('task_id'), 'file_name': task['file_name'], 'status': status,
            'pages': task.get('pages', ''), 'price': task.get('price', '')
        })
        if status not in [STATUS['READY'], STATUS['ERROR_CONVERSION'], STATUS['ERROR_PAGE_COUNT']]:
            job_is_complete = False

    return jsonify({'job_id': job_id, 'tasks': tasks_for_ui, 'is_complete': job_is_complete})

@app.route('/calculate_summary', methods=['POST'])
def calculate_summary():
    data = request.get_json()
    job_id = data.get('job_id')
    tasks_with_new_options = data.get('tasks')

    if not all([job_id, tasks_with_new_options]):
        return jsonify({'success': False, 'error': 'Données manquantes pour le calcul'}), 400

    tasks_ready_for_print = []
    total_price = 0.0

    all_tasks_from_history = []
    if os.path.exists(HISTORY_FILE):
        with history_lock:
            with open(HISTORY_FILE, 'r', newline='', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                all_tasks_from_history = [row for row in reader if row.get('job_id') == job_id]

    history_map = {task['task_id']: task for task in all_tasks_from_history}

    for task_options in tasks_with_new_options:
        task_id = task_options.get('task_id')
        original_task_data = history_map.get(task_id)

        if not original_task_data or original_task_data.get('status') != STATUS['READY']:
            continue

        options = task_options.get('options', {})
        pages = int(original_task_data.get('pages', 0))
        is_color = options.get('color') == 'color'
        is_duplex = options.get('siding') == 'recto_verso'
        copies = int(options.get('copies', 1))
        page_mode = options.get('pagemode', 'all')
        start_page = options.get('startpage', '1')
        end_page = options.get('endpage', str(pages))

        pages_a_imprimer = pages
        if page_mode == 'range' and start_page.isdigit() and end_page.isdigit():
            try: pages_a_imprimer = int(end_page) - int(start_page) + 1
            except: pages_a_imprimer = pages

        prix_par_page = PRIX_COULEUR if is_color else PRIX_NOIR_BLANC
        prix_tache = pages_a_imprimer * prix_par_page * copies
        total_price += prix_tache

        pdf_filename = f"{os.path.splitext(original_task_data['secure_filename'])[0]}.pdf"
        final_pdf_path = os.path.join(CONVERTED_FOLDER, pdf_filename)

        tasks_ready_for_print.append({
            'path': final_pdf_path, 'name': original_task_data['file_name'], 'pages': pages, 'copies': copies,
            'is_color': is_color, 'is_duplex': is_duplex, 'prix': prix_tache,
            'paper_size': options.get('papersize', '2'), 'page_mode': page_mode,
            'start_page': start_page, 'end_page': end_page,
            'job_id': job_id, 'timestamp': original_task_data['timestamp'], 'client_name': original_task_data['client_name'],
            'file_name': original_task_data['file_name'], 'task_id': task_id
        })

    if not tasks_ready_for_print:
        return jsonify({'success': False, 'error': 'Aucune tâche valide trouvée pour le résumé.'}), 400

    print_job_summary = {
        'tasks': tasks_ready_for_print, 'prix_total': total_price,
        'client_name': history_map[tasks_ready_for_print[0]['task_id']]['client_name'],
        'timestamp': history_map[tasks_ready_for_print[0]['task_id']]['timestamp'],
        'job_id': job_id
    }
    session['print_job'] = print_job_summary

    return jsonify({'success': True, 'print_job_summary': print_job_summary})

@app.route('/print', methods=['POST'])
def execute_print():
    print_job = session.get('print_job')
    if not print_job:
        return jsonify({'success': False, 'error': 'Session expirée. Veuillez recommencer.'}), 400

    print_thread = threading.Thread(target=_run_print_job, args=(print_job,))
    print_thread.start()
    session.pop('print_job', None)
    return jsonify({'success': True})

def get_task_from_history(id_type, id_value):
    if not os.path.exists(HISTORY_FILE): return None
    with history_lock:
        with open(HISTORY_FILE, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if row.get(id_type) == id_value:
                    return row
    return None

# --- Routes Admin ---
@app.route('/download/<task_id>')
def download_file(task_id):
    if not session.get('is_admin'):
        return "Accès non autorisé", 403

    task_info = get_task_from_history('task_id', task_id)
    if not task_info:
        return "Tâche introuvable.", 404

    secure_filename = task_info.get('secure_filename')
    pdf_filename = f"{os.path.splitext(secure_filename)[0]}.pdf"
    pdf_path = os.path.join(CONVERTED_FOLDER, pdf_filename)
    if os.path.exists(pdf_path):
        return send_from_directory(CONVERTED_FOLDER, pdf_filename, as_attachment=False)

    original_path = os.path.join(UPLOAD_FOLDER, secure_filename)
    if os.path.exists(original_path):
        return send_from_directory(UPLOAD_FOLDER, secure_filename, as_attachment=True)

    return "Fichier introuvable.", 404

# --- FONCTION DE RÉIMPRESSION RESTAURÉE ---
@app.route('/reprint', methods=['POST'])
def reprint_task():
    if not session.get('is_admin'): return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    data = request.get_json()
    task_id = data.get('task_id')
    if not task_id: return jsonify({'success': False, 'error': 'task_id manquant.'})

    task_info = get_task_from_history('task_id', task_id)
    if not task_info: return jsonify({'success': False, 'error': f'Tâche {task_id} introuvable.'})

    secure_filename = task_info.get('secure_filename')
    pdf_filename = f"{os.path.splitext(secure_filename)[0]}.pdf"
    pdf_path = os.path.join(CONVERTED_FOLDER, pdf_filename)
    if not os.path.exists(pdf_path): return jsonify({'success': False, 'error': f'Fichier PDF {pdf_filename} introuvable.'})

    reprint_job = {
        'tasks': [{'path': pdf_path, 'name': task_info['file_name'], 'copies': 1, 'pages': count_pages(pdf_path),
            'is_color': data.get('is_color', False), 'is_duplex': data.get('is_duplex', False),
            'paper_size': data.get('paper_size', '2'), 'page_mode': 'all',
            'job_id': task_info.get('job_id'), 'task_id': task_id, 'timestamp': task_info.get('timestamp'),
            'client_name': task_info.get('client_name'), 'file_name': task_info['file_name'] }]
    }
    print_thread = threading.Thread(target=_run_print_job, args=(reprint_job,))
    print_thread.start()
    return jsonify({'success': True})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USERNAME and request.form.get('password') == ADMIN_PASSWORD:
            session['is_admin'] = True; return jsonify({'success': True})
        else: return jsonify({'success': False, 'error': 'Identifiants incorrects'})
    return render_template('admin.html', is_logged_in=session.get('is_admin', False))

@app.route('/api/admin_data')
def admin_data_api():
    if not session.get('is_admin'): return jsonify({'error': 'Non autorisé'}), 403
    history = []
    if os.path.exists(HISTORY_FILE):
        with history_lock:
            with open(HISTORY_FILE, 'r', newline='', encoding='utf-8') as csvfile:
                try:
                    history = list(csv.DictReader(csvfile))
                    history.reverse()
                except Exception as e:
                    return jsonify({'error': 'Fichier historique corrompu'}), 500

    grouped_commands = OrderedDict()
    for row in history:
        key = row.get('job_id')
        if not key: continue
        if key not in grouped_commands:
            grouped_commands[key] = {
                'job_id': key, 'timestamp': row['timestamp'], 'client_name': row['client_name'],
                'total_price': 0.0, 'files': [], 'job_status': 'success'
            }
        grouped_commands[key]['files'].append(row)
        if row.get('price') and 'ERREUR' not in row.get('status', ''):
             try:
                 grouped_commands[key]['total_price'] += float(row.get('price', 0))
             except (ValueError, TypeError):
                 pass
        if 'ERREUR' in row.get('status', ''): grouped_commands[key]['job_status'] = 'error'
        elif 'EN_ATTENTE' in row.get('status', '') and grouped_commands[key]['job_status'] != 'error':
            grouped_commands[key]['job_status'] = 'pending'

    final_commands = list(grouped_commands.values())
    total_revenue = sum(cmd['total_price'] for cmd in final_commands)
    total_pages_printed = sum(
        int(f.get('pages', 0) or 0) * int(f.get('copies', 1) or 1) for cmd in final_commands for f in cmd['files']
        if f.get('status') == STATUS['PRINT_SUCCESS']
    )
    return jsonify({'commands': final_commands, 'total_revenue': f"{total_revenue:.2f}", 'total_pages': total_pages_printed})

@app.route('/api/delete_task/<task_id>', methods=['POST'])
def delete_task(task_id):
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    rows_to_keep = []
    task_found = False
    if os.path.exists(HISTORY_FILE):
        with history_lock:
            try:
                with open(HISTORY_FILE, 'r', newline='', encoding='utf-8') as csvfile:
                    reader = csv.DictReader(csvfile)
                    fieldnames = reader.fieldnames or []
                    for row in reader:
                        if row.get('task_id') == task_id:
                            task_found = True
                        else:
                            rows_to_keep.append(row)

                if task_found:
                    temp_file = HISTORY_FILE + '.tmp'
                    with open(temp_file, 'w', newline='', encoding='utf-8') as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        writer.writeheader()
                        writer.writerows(rows_to_keep)
                    shutil.move(temp_file, HISTORY_FILE)
                    return jsonify({'success': True})
                else:
                    return jsonify({'success': False, 'error': 'Tâche non trouvée'}), 404
            except Exception as e:
                return jsonify({'success': False, 'error': 'Erreur serveur lors de la suppression'}), 500
    return jsonify({'success': False, 'error': 'Historique introuvable'}), 404

@app.route('/api/delete_all_tasks', methods=['POST'])
def delete_all_tasks():
    if not session.get('is_admin'):
        return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    try:
        with history_lock:
            if os.path.exists(HISTORY_FILE):
                os.remove(HISTORY_FILE)
        fieldnames = ['job_id', 'task_id', 'timestamp', 'client_name', 'file_name', 'secure_filename', 'pages', 'copies', 'color', 'duplex', 'price', 'status', 'paper_size', 'page_mode', 'start_page', 'end_page']
        with open(HISTORY_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': 'Erreur serveur lors de la suppression'}), 500

@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
