import os
import time
import sys
import csv
import subprocess
import shutil
from datetime import datetime
import pathlib
from collections import OrderedDict

# --- Imports (Ajout de send_from_directory) ---
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import Select
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from PyPDF2 import PdfReader

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

for folder in [UPLOAD_FOLDER, CONVERTED_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods'}

# --- Fonctions utilitaires ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def count_pages(filepath):
    try:
        with open(filepath, 'rb') as f:
            reader = PdfReader(f)
            return len(reader.pages)
    except Exception:
        return 0

def save_to_history(job):
    file_exists = os.path.isfile(HISTORY_FILE)
    try:
        with open(HISTORY_FILE, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['timestamp', 'client_name', 'file_name', 'pages', 'copies', 'color', 'duplex', 'price']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for task in job['tasks']:
                 writer.writerow({
                    'timestamp': job.get('timestamp'), 'client_name': job.get('client_name', 'Inconnu'),
                    'file_name': task['name'], 'pages': task['pages'], 'copies': task.get('copies', 1),
                    'color': 'Couleur' if task['is_color'] else 'N&B', 'duplex': 'Recto-Verso' if task['is_duplex'] else 'Recto',
                    'price': f"{task.get('prix', 0):.2f}"
                })
    except Exception as e:
        print(f"ERREUR lors de l'enregistrement : {e}")

def convert_to_pdf(source_path):
    filename = os.path.basename(source_path)
    pdf_path = os.path.join(CONVERTED_FOLDER, f"{os.path.splitext(filename)[0]}.pdf")
    if os.path.splitext(filename)[1].lower() == '.pdf':
        shutil.copy(source_path, pdf_path)
        return pdf_path
    lo_command = "C:\\Program Files\\LibreOffice\\program\\soffice.exe"
    if not os.path.exists(lo_command): return None
    user_profile_path = os.path.join(os.getcwd(), 'lo_profile')
    user_profile_url = pathlib.Path(user_profile_path).as_uri()
    try:
        command = [lo_command, f'-env:UserInstallation={user_profile_url}', '--headless', '--convert-to', 'pdf:writer_pdf_Export', '--outdir', CONVERTED_FOLDER, source_path]
        subprocess.run(command, check=True, timeout=120)
        timeout = 20; start_time = time.time()
        while time.time() - start_time < timeout:
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                time.sleep(1)
                if os.path.exists(user_profile_path): shutil.rmtree(user_profile_path)
                return pdf_path
            time.sleep(0.5)
        if os.path.exists(user_profile_path): shutil.rmtree(user_profile_path)
        return None
    except Exception:
        if os.path.exists(user_profile_path): shutil.rmtree(user_profile_path)
        return None

# --- Fonction d'impression refactorisée avec gestion de la plage ---
def _run_print_job(job):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--window-size=1920,1080")
    options.add_argument('--no-sandbox'); options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--ignore-certificate-errors'); options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = None
    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        wait = WebDriverWait(driver, 60)
        num_tasks = len(job['tasks'])
        for i, task in enumerate(job['tasks']):
            driver.get(URL_PDF_PRINT)
            wait.until(EC.presence_of_element_located((By.XPATH, "//input[contains(@value, \"Démarrer l'impression\")]")))
            Select(driver.find_element(By.CSS_SELECTOR, "select[name='ColorMode']")).select_by_value("0" if task['is_color'] else "1")
            if task['is_duplex']:
                if not driver.find_element(By.ID, "DuplexMode").is_selected(): driver.find_element(By.ID, "DuplexMode").click()
                Select(driver.find_element(By.CSS_SELECTOR, "select[name='DuplexType']")).select_by_value("2")
            Select(driver.find_element(By.CSS_SELECTOR, "select[name='MediaSize']")).select_by_value(task.get('paper_size', '2'))
            copies_input = driver.find_element(By.ID, "Copies")
            copies_input.clear()
            copies_input.send_keys(str(task.get('copies', 1)))
            
            if task.get('page_mode') == 'range':
                driver.find_element(By.ID, 'PageMode2').click()
                driver.find_element(By.ID, 'StartPage').send_keys(task.get('start_page', '1'))
                driver.find_element(By.ID, 'EndPage').send_keys(task.get('end_page', '1'))
            else:
                driver.find_element(By.ID, 'PageMode1').click()

            driver.find_element(By.NAME, "File").send_keys(os.path.abspath(task['path']))
            driver.find_element(By.XPATH, "//input[contains(@value, \"Démarrer l'impression\")]").click()
            wait.until(EC.url_contains("pprint.cgi"))
            return_button_xpath = "//input[contains(@value, 'Retour à la page précédente')]"
            wait.until(EC.element_to_be_clickable((By.XPATH, return_button_xpath)))
            if i < num_tasks - 1:
                driver.find_element(By.XPATH, return_button_xpath).click()
        return True
    except Exception as e:
        import traceback; traceback.print_exc()
        if driver: driver.save_screenshot(f"selenium_error_{int(time.time())}.png")
        return False
    finally:
        if driver: driver.quit()

# --- Routes Flask ---
@app.route('/')
def index():
    return render_template('index.html', prix_nb=PRIX_NOIR_BLANC, prix_c=PRIX_COULEUR, success_message=request.args.get('success_message'), error_message=request.args.get('error_message'))

@app.route('/calculate', methods=['POST'])
def calculate_price():
    client_name = request.form.get('client_name')
    if not client_name: return jsonify({'error': "Veuillez renseigner votre nom."}), 400
    files = request.files.getlist('files[]')
    if not files: return jsonify({'error': "Veuillez sélectionner au moins un fichier."}), 400
    tasks, prix_total = [], 0
    for i, file in enumerate(files):
        if file and allowed_file(file.filename):
            original_filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(original_filepath)
            final_pdf_path = convert_to_pdf(original_filepath)
            if not final_pdf_path: continue
            pages = count_pages(final_pdf_path)
            if pages == 0: continue
            is_color = request.form.get(f'color_{i}') == 'color'
            is_duplex = request.form.get(f'siding_{i}') == 'recto_verso'
            copies = int(request.form.get(f'copies_{i}', 1))
            paper_size = request.form.get(f'papersize_{i}', '2')
            page_mode = request.form.get(f'pagemode_{i}', 'all')
            start_page = request.form.get(f'startpage_{i}', '1')
            end_page = request.form.get(f'endpage_{i}', str(pages))
            
            pages_a_imprimer = pages
            if page_mode == 'range':
                try: pages_a_imprimer = int(end_page) - int(start_page) + 1
                except: pages_a_imprimer = pages
            
            prix_par_page = PRIX_COULEUR if is_color else PRIX_NOIR_BLANC
            prix_tache = pages_a_imprimer * prix_par_page * copies
            prix_total += prix_tache
            tasks.append({
                'path': final_pdf_path, 'name': file.filename, 'pages': pages, 'copies': copies,
                'is_color': is_color, 'is_duplex': is_duplex, 'prix': prix_tache, 'paper_size': paper_size,
                'page_mode': page_mode, 'start_page': start_page, 'end_page': end_page
            })
    if not tasks: return jsonify({'error': "Impossible de traiter les fichiers."}), 400
    session['print_job'] = {'tasks': tasks, 'prix_total': prix_total, 'client_name': client_name, 'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    return jsonify(session.get('print_job'))

@app.route('/print', methods=['POST'])
def execute_print():
    print_job = session.get('print_job')
    if not print_job: return redirect(url_for('index', error_message="Session expirée."))
    success = _run_print_job(print_job)
    if success:
        save_to_history(print_job)
        session.pop('print_job', None)
        return redirect(url_for('index', success_message="Impression lancée !"))
    else:
        return redirect(url_for('index', error_message="Erreur lors de l'impression."))

# --- Routes Admin ---
@app.route('/download/<path:filename>')
def download_file(filename):
    if not session.get('is_admin'): return "Accès non autorisé", 403
    base, ext = os.path.splitext(filename)
    pdf_filename = f"{base}.pdf"
    return send_from_directory(CONVERTED_FOLDER, pdf_filename, as_attachment=False)

@app.route('/reprint', methods=['POST'])
def reprint_task():
    if not session.get('is_admin'): return jsonify({'success': False, 'error': 'Non autorisé'}), 403
    data = request.get_json()
    original_filename = data.get('filename')
    base, ext = os.path.splitext(original_filename)
    pdf_filename = f"{base}.pdf"
    pdf_path = os.path.join(CONVERTED_FOLDER, pdf_filename)
    if not os.path.exists(pdf_path): return jsonify({'success': False, 'error': f'Fichier {pdf_filename} introuvable.'})
    reprint_job = {
        'client_name': data.get('client_name'),
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S (Réimp.)"),
        'tasks': [{'path': pdf_path, 'name': original_filename, 'copies': 1, 'pages': count_pages(pdf_path), 'is_color': data.get('is_color', False), 'is_duplex': data.get('is_duplex', False)}]
    }
    success = _run_print_job(reprint_job)
    if success:
        save_to_history(reprint_job)
    return jsonify({'success': success})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USERNAME and request.form.get('password') == ADMIN_PASSWORD:
            session['is_admin'] = True
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Identifiants incorrects'})
    is_logged_in = session.get('is_admin', False)
    return render_template('admin.html', is_logged_in=is_logged_in)

@app.route('/api/admin_data')
def admin_data_api():
    if not session.get('is_admin'): return jsonify({'error': 'Non autorisé'}), 403
    history = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', newline='', encoding='utf-8') as csvfile:
            history = list(csv.DictReader(csvfile))
        history.reverse()

    grouped_commands = OrderedDict()
    for row in history:
        key = f"{row['timestamp']}_{row['client_name']}"
        if key not in grouped_commands:
            grouped_commands[key] = {
                'timestamp': row['timestamp'],
                'client_name': row['client_name'],
                'total_price': 0.0,
                'files': []
            }
        grouped_commands[key]['files'].append(row)
        grouped_commands[key]['total_price'] += float(row.get('price', 0))

    final_commands = list(grouped_commands.values())
    total_revenue = sum(cmd['total_price'] for cmd in final_commands)
    total_pages = sum(int(f.get('pages', 0)) * int(f.get('copies', 1)) for cmd in final_commands for f in cmd['files'])
    
    return jsonify({'commands': final_commands, 'total_revenue': f"{total_revenue:.2f}", 'total_pages': total_pages})

@app.route('/logout')
def logout():
    session.pop('is_admin', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
