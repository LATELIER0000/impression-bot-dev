// static/js/admin.js
document.addEventListener('DOMContentLoaded', function() {
    const loginSection = document.getElementById('login-section');
    const adminPanel = document.getElementById('admin-panel');
    const loginForm = document.getElementById('login-form');
    const loginError = document.getElementById('login-error');

    let refreshInterval;

    function formatBytes(bytes, d = 2) {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const s = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return `${parseFloat((bytes / Math.pow(k, i)).toFixed(d))} ${s[i]}`;
    }

    function initializeFileExplorer() {
        const tbody = document.getElementById('file-explorer-tbody');
        if (!tbody) return;

        fetch('/api/browse_files')
            .then(res => res.json())
            .then(files => {
                if (files.error) throw new Error(files.error);
                if (files.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted p-4">Aucun fichier trouvé.</td></tr>';
                    return;
                }
                tbody.innerHTML = files.map(file => {
                    const previewUrl = `/api/download_raw_file?path=${encodeURIComponent(file.path)}`;
                    const downloadUrl = `/api/download_raw_file?path=${encodeURIComponent(file.path)}&dl=1`;
                    return `<tr><td style="word-break: break-all;"><a href="${previewUrl}" target="_blank" class="text-decoration-none" title="Ouvrir le fichier"><i class="bi bi-file-earmark-text"></i> ${file.path.replace(/\\/g, '/')}</a></td><td>${formatBytes(file.size)}</td><td>${file.modified}</td><td class="text-end"><a href="${downloadUrl}" class="btn btn-sm btn-outline-secondary" title="Télécharger"><i class="bi bi-download"></i></a></td></tr>`;
                }).join('');
            })
            .catch(err => {
                tbody.innerHTML = '<tr><td colspan="4" class="text-center text-danger p-4">Erreur de chargement des fichiers.</td></tr>';
                console.error("Erreur de l'explorateur:", err);
            });
    }

    function initializeAdminPanel() {
        const refreshBtn = document.getElementById('refresh-btn');
        const deleteAllBtn = document.getElementById('delete-all-btn');
        const allCommandsContainer = document.getElementById('all-commands-container');
        const uploadCommandsContainer = document.getElementById('upload-commands-container');
        const emailCommandsContainer = document.getElementById('email-commands-container');
        const reprintToastEl = document.getElementById('reprintToast');
        const reprintToast = reprintToastEl ? new bootstrap.Toast(reprintToastEl) : null;
        let currentPopover = null;

        function refreshAllData() {
            fetchAdminData();
            initializeFileExplorer();
        }

        const createCommandCardHTML = (command) => {
            const collapseId = `command-details-${command.job_id}`;
            const openCollapses = new Set(Array.from(document.querySelectorAll('.collapse.show')).map(el => el.id));
            const showClass = openCollapses.has(collapseId) ? 'show' : '';

            const filesHTML = command.files.map(file => {
                let statusBadge;
                const status = file.status || 'INCONNU';
                const isPrintable = !['ERREUR_CONVERSION', 'ERREUR_FICHIER_VIDE', 'ERREUR_LECTURE_FATALE'].includes(status) && file.task_id;
                if (status.includes('ERREUR')) statusBadge = `<span class="badge bg-danger">${status.replace(/_/g, ' ')}</span>`;
                else if (status.includes('IMPRIME')) statusBadge = `<span class="badge bg-success">Imprimé</span>`;
                else if (status.includes('IMPRESSION_EN_COURS')) statusBadge = `<span class="badge bg-info text-dark">Impression...</span>`;
                else statusBadge = `<span class="badge bg-secondary">${status.replace(/_/g, ' ')}</span>`;
                const priceDisplay = file.price ? `<small class="text-muted">(${(+file.price).toFixed(2)}€)</small>` : '';
                const downloadLink = file.task_id ? `<a href="/download/${file.task_id}" target="_blank" class="text-decoration-none">${file.file_name}</a>` : file.file_name;
                const pageDisplay = file.pages > 0 ? `<small class="text-muted ms-2">| ${file.pages} p.</small>` : '';
                return `<li class="list-group-item d-flex justify-content-between align-items-center flex-wrap"><div class="me-auto" style="word-break: break-all; padding-right: 1rem;">${downloadLink} ${pageDisplay} ${priceDisplay}<div class="mt-1">${statusBadge}</div></div><div class="btn-group mt-1 mt-sm-0" role="group"><button class="btn btn-sm btn-outline-secondary reprint-btn" title="Réimprimer ce fichier" data-task-id="${file.task_id}" ${!isPrintable ? 'disabled' : ''}><i class="bi bi-printer"></i></button><button class="btn btn-sm btn-outline-danger delete-task-btn" title="Supprimer tâche" data-task-id="${file.task_id}" data-filename="${file.file_name}" ${!file.task_id ? 'disabled' : ''}><i class="bi bi-x-lg"></i></button></div></li>`;
            }).join('');

            const cardStatusClass = `status-${command.job_status || 'unknown'}`;
            // MODIFIÉ : On utilise 'username' comme titre principal
            const title = command.username;
            const subtitle = command.timestamp;
            const isEmail = command.source === 'email';
            const sourceIcon = isEmail ? '<i class="bi bi-envelope-at-fill text-muted me-1" title="Source: Email"></i>' : '<i class="bi bi-upload text-muted me-1" title="Source: Upload"></i>';
            const subjectHTML = isEmail && command.email_subject
                ? `<small class="d-block text-muted fst-italic mt-1" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${command.email_subject}">Objet : ${command.email_subject}</small>`
                : '';

            return `<div class="card shadow-sm mb-3 ${cardStatusClass}"><div class="card-body"><div class="d-flex justify-content-between align-items-center"><a href="#" class="text-decoration-none text-dark flex-grow-1" data-bs-toggle="collapse" data-bs-target="#${collapseId}"><h5 class="card-title mb-0">${sourceIcon}${title}</h5><small class="text-muted">${subtitle}</small>${subjectHTML}</a><div class="text-end ms-3"><strong class="fs-5">${command.total_price.toFixed(2)} €</strong><div class="small text-muted">${command.files.length} fichier(s) <i class="bi bi-chevron-down"></i></div></div></div><div class="collapse ${showClass}" id="${collapseId}"><hr><div class="d-flex justify-content-end mb-3"><button class="btn btn-sm btn-dark reprint-job-btn" data-job-id="${command.job_id}"><i class="bi bi-printer-fill"></i> Réimprimer toute la commande</button></div><ul class="list-group list-group-flush">${filesHTML}</ul></div></div></div>`;
        };

        const fetchAdminData = () => {
            fetch('/api/admin_data')
                .then(res => {
                    if (res.status === 401 || res.status === 403) window.location.reload();
                    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
                    return res.json();
                })
                .then(data => {
                    if (data.error) throw new Error(data.error);
                    document.getElementById('total-revenue-display').textContent = `${data.total_revenue} €`;
                    document.getElementById('total-pages-display').textContent = data.total_pages;
                    const allCombinedCommands = [...(data.upload_commands || []), ...(data.email_commands || [])];
                    deleteAllBtn.disabled = allCombinedCommands.length === 0;
                    if (allCombinedCommands.length === 0) {
                        allCommandsContainer.innerHTML = '<p class="text-center text-muted p-4">Aucune commande pour le moment.</p>';
                    } else {
                        allCombinedCommands.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
                        allCommandsContainer.innerHTML = allCombinedCommands.map(createCommandCardHTML).join('');
                    }
                    if (!data.upload_commands || data.upload_commands.length === 0) {
                        uploadCommandsContainer.innerHTML = '<p class="text-center text-muted p-4">Aucune commande par upload.</p>';
                    } else {
                        uploadCommandsContainer.innerHTML = data.upload_commands.map(createCommandCardHTML).join('');
                    }
                    if (!data.email_commands || data.email_commands.length === 0) {
                        emailCommandsContainer.innerHTML = '<p class="text-center text-muted p-4">Aucune commande par email.</p>';
                    } else {
                        emailCommandsContainer.innerHTML = data.email_commands.map(createCommandCardHTML).join('');
                    }
                })
                .catch(error => {
                    console.error('Erreur lors de la récupération des données admin:', error);
                    allCommandsContainer.innerHTML = '<div class="alert alert-danger">Impossible de charger l\'historique.</div>';
                });
        };

        refreshBtn.addEventListener('click', refreshAllData);
        deleteAllBtn.addEventListener('click', () => {
             if (confirm("ATTENTION !\n\nÊtes-vous sûr de vouloir effacer TOUT l'historique ?\n\nCETTE ACTION EST IRRÉVERSIBLE.")) {
                fetch('/api/delete_all_tasks', { method: 'POST' }).then(res => res.json()).then(data => {
                    if (data.success) refreshAllData(); else alert(`Erreur: ${data.error}`);
                });
            }
        });
        function getPopoverContent(id, type) {
            const idAttribute = type === 'task' ? `data-task-id="${id}"` : `data-job-id="${id}"`;
            return `<div class="reprint-popover-body"><div class="mb-2"><label class="form-label">Couleur</label><div class="reprint-option-group"><button type="button" class="option-btn active" data-name="is_color" data-value="false">N&B</button><button type="button" class="option-btn" data-name="is_color" data-value="true">Couleur</button></div></div><div class="mb-3"><label class="form-label">Recto/Verso</label><div class="reprint-option-group"><button type="button" class="option-btn active" data-name="is_duplex" data-value="false">Recto</button><button type="button" class="option-btn" data-name="is_duplex" data-value="true">R/V</button></div></div><div class="mb-3"><label class="form-label">Copies</label><input type="number" class="form-control form-control-sm popover-copies-input" value="1" min="1"></div><button class="btn btn-sm btn-dark w-100 reprint-popover-confirm-btn" ${idAttribute}>Valider</button></div>`;
        }
        adminPanel.addEventListener('click', (event) => {
            const reprintBtn = event.target.closest('.reprint-btn');
            const reprintJobBtn = event.target.closest('.reprint-job-btn');
            const deleteTaskBtn = event.target.closest('.delete-task-btn');
            let button = null; let type = ''; let id = '';
            if (reprintBtn) { button = reprintBtn; type = 'task'; id = button.dataset.taskId; }
            if (reprintJobBtn) { button = reprintJobBtn; type = 'job'; id = button.dataset.jobId; }
            if (button) {
                event.preventDefault();
                if (currentPopover && currentPopover._element !== button) { currentPopover.dispose(); }
                currentPopover = new bootstrap.Popover(button, { html: true, sanitize: false, content: getPopoverContent(id, type), title: 'Options de réimpression', placement: 'left' });
                currentPopover.show();
                return;
            }
            if (deleteTaskBtn) {
                if (currentPopover) currentPopover.dispose();
                const { taskId, filename } = deleteTaskBtn.dataset;
                if (confirm(`Supprimer la tâche pour "${filename}" ?`)) {
                    fetch(`/api/delete_task/${taskId}`, { method: 'POST' }).then(res => res.json()).then(data => { if (data.success) refreshAllData(); else alert(`Erreur: ${data.error}`); });
                }
            }
        });
        document.body.addEventListener('click', function(event) {
            const target = event.target;
            const confirmBtn = target.closest('.reprint-popover-confirm-btn');
            if (!target.closest('.popover') && currentPopover) {
                if (!currentPopover._element.contains(target)) { currentPopover.dispose(); currentPopover = null; }
                return;
            }
            if (target.classList.contains('option-btn')) {
                const group = target.parentElement;
                group.querySelectorAll('.option-btn').forEach(btn => btn.classList.remove('active'));
                target.classList.add('active');
            }
            if (confirmBtn) {
                const popover = confirmBtn.closest('.popover');
                const options = { copies: parseInt(popover.querySelector('.popover-copies-input').value) || 1, is_color: popover.querySelector('.option-btn[data-name="is_color"].active').dataset.value === 'true', is_duplex: popover.querySelector('.option-btn[data-name="is_duplex"].active').dataset.value === 'true' };
                let url, payload;
                const taskId = confirmBtn.dataset.taskId;
                const jobId = confirmBtn.dataset.jobId;
                if (taskId) { url = '/reprint'; payload = { task_id: taskId, ...options }; }
                else if (jobId) { url = '/api/reprint_job'; payload = { job_id: jobId, options: options }; }
                else { return; }
                fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
                    .then(res => { if (!res.ok) throw new Error(`Erreur serveur (${res.status})`); return res.json(); })
                    .then(result => { if (result.success) { reprintToast.show(); } else { alert(`Erreur: ${result.error || 'Une erreur est survenue.'}`); } })
                    .catch(err => alert(`Erreur de communication: ${err.message}`))
                    .finally(() => { if (currentPopover) { currentPopover.dispose(); currentPopover = null; } });
            }
        });
        document.addEventListener("visibilitychange", () => {
            if (document.hidden) {
                clearInterval(refreshInterval);
            } else {
                refreshAllData();
                refreshInterval = setInterval(refreshAllData, 5000);
            }
        });
        refreshAllData();
        refreshInterval = setInterval(refreshAllData, 5000);
    }

    function showAdminPanel() {
        loginSection.classList.add('d-none');
        adminPanel.classList.remove('d-none');
        initializeAdminPanel();
    }

    if (loginForm) {
        loginForm.addEventListener('submit', function(event) {
            event.preventDefault();
            const formData = new FormData(loginForm);
            fetch('/login', { method: 'POST', body: formData })
                .then(response => response.json())
                .then(data => {
                    if (data.success) { showAdminPanel(); }
                    else { loginError.textContent = data.error || "Une erreur est survenue."; loginError.classList.remove('d-none'); }
                })
                .catch(err => {
                    loginError.textContent = "Erreur de connexion avec le serveur.";
                    loginError.classList.remove('d-none');
                });
        });
    }

    if (typeof isUserLoggedIn !== 'undefined' && isUserLoggedIn) {
        showAdminPanel();
    }
});
