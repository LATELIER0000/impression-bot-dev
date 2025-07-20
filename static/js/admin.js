// static/js/admin.js
document.addEventListener('DOMContentLoaded', function() {
    const loginSection = document.getElementById('login-section');
    const adminPanel = document.getElementById('admin-panel');
    const loginForm = document.getElementById('login-form');
    const loginError = document.getElementById('login-error');

    let refreshInterval;

    function initializeAdminPanel() {
        const refreshBtn = document.getElementById('refresh-btn');
        const deleteAllBtn = document.getElementById('delete-all-btn');

        // NOUVEAU: Sélection des deux conteneurs
        const uploadCommandsContainer = document.getElementById('upload-commands-container');
        const emailCommandsContainer = document.getElementById('email-commands-container');

        const reprintToastEl = document.getElementById('reprintToast');
        const reprintToast = reprintToastEl ? new bootstrap.Toast(reprintToastEl) : null;
        let currentPopover = null;

        // NOUVEAU : Fonction réutilisable pour générer le HTML d'une commande
        const createCommandCardHTML = (command) => {
            const collapseId = `command-details-${command.job_id}`;
            const isEmail = command.source === 'email';

            // On conserve les états ouverts pour le rafraîchissement
            const openCollapses = new Set(Array.from(document.querySelectorAll('.collapse.show')).map(el => el.id));
            const showClass = openCollapses.has(collapseId) ? 'show' : '';

            const filesHTML = command.files.map(file => {
                let statusBadge;
                const status = file.status || 'INCONNU';
                const unprintableStatuses = ['ERREUR_CONVERSION', 'ERREUR_FICHIER_VIDE', 'ERREUR_LECTURE_FATALE'];
                const isPrintable = !unprintableStatuses.includes(status) && file.task_id;

                if (status.includes('ERREUR')) statusBadge = `<span class="badge bg-danger">${status.replace(/_/g, ' ')}</span>`;
                else if (status.includes('IMPRIME')) statusBadge = `<span class="badge bg-success">Imprimé</span>`;
                else if (status.includes('IMPRESSION_EN_COURS')) statusBadge = `<span class="badge bg-info text-dark">Impression...</span>`;
                else statusBadge = `<span class="badge bg-secondary">${status.replace(/_/g, ' ')}</span>`;

                const priceDisplay = file.price ? `<small class="text-muted">(${(+file.price).toFixed(2)}€)</small>` : '';
                const downloadLink = file.task_id ? `<a href="/download/${file.task_id}" target="_blank" class="text-decoration-none">${file.file_name}</a>` : file.file_name;

                const pageDisplay = file.pages > 0 ? `<small class="text-muted ms-2">| ${file.pages} p.</small>` : '';

                return `
                    <li class="list-group-item d-flex justify-content-between align-items-center flex-wrap">
                        <div class="me-auto" style="word-break: break-all; padding-right: 1rem;">
                            ${downloadLink} ${pageDisplay} ${priceDisplay}
                            <div class="mt-1">${statusBadge}</div>
                        </div>
                        <div class="btn-group mt-1 mt-sm-0" role="group">
                            <button class="btn btn-sm btn-outline-secondary reprint-btn" title="Réimprimer ce fichier"
                                data-task-id="${file.task_id}" ${!isPrintable ? 'disabled' : ''}>
                                <i class="bi bi-printer"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-danger delete-task-btn" title="Supprimer tâche"
                                data-task-id="${file.task_id}" data-filename="${file.file_name}" ${!file.task_id ? 'disabled' : ''}>
                                <i class="bi bi-x-lg"></i>
                            </button>
                        </div>
                    </li>`;
            }).join('');

            const cardStatusClass = command.job_status === 'error' ? 'status-error' : (command.job_status === 'pending' ? 'status-pending' : '');

            // Affichage du nom du client ou du sujet de l'email
            const title = isEmail ? command.email_subject || 'Email sans sujet' : command.client_name;
            const subtitle = isEmail ? command.client_name : command.timestamp;

            return `
                <div class="card shadow-sm mb-3 ${cardStatusClass}">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center">
                            <a href="#" class="text-decoration-none text-dark flex-grow-1" data-bs-toggle="collapse" data-bs-target="#${collapseId}">
                                <h5 class="card-title mb-0">${title}</h5>
                                <small class="text-muted">${subtitle}</small>
                            </a>
                            <div class="text-end ms-3">
                                <strong class="fs-5">${command.total_price.toFixed(2)} €</strong>
                                <div class="small text-muted">${command.files.length} fichier(s) <i class="bi bi-chevron-down"></i></div>
                            </div>
                        </div>
                        <div class="collapse ${showClass}" id="${collapseId}">
                            <hr>
                            <div class="d-flex justify-content-end mb-3">
                                <button class="btn btn-sm btn-dark reprint-job-btn" data-job-id="${command.job_id}">
                                    <i class="bi bi-printer-fill"></i> Réimprimer toute la commande
                                </button>
                            </div>
                            <ul class="list-group list-group-flush">${filesHTML}</ul>
                        </div>
                    </div>
                </div>`;
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

                    const allCommands = [...(data.upload_commands || []), ...(data.email_commands || [])];
                    deleteAllBtn.disabled = allCommands.length === 0;

                    // Affichage des commandes par Upload
                    if (!data.upload_commands || data.upload_commands.length === 0) {
                        uploadCommandsContainer.innerHTML = '<p class="text-center text-muted">Aucune commande par upload.</p>';
                    } else {
                        uploadCommandsContainer.innerHTML = data.upload_commands.map(createCommandCardHTML).join('');
                    }

                    // Affichage des commandes par Email
                    if (!data.email_commands || data.email_commands.length === 0) {
                        emailCommandsContainer.innerHTML = '<p class="text-center text-muted">Aucune commande par email.</p>';
                    } else {
                        emailCommandsContainer.innerHTML = data.email_commands.map(createCommandCardHTML).join('');
                    }
                })
                .catch(error => {
                    console.error('Erreur lors de la récupération des données admin:', error);
                    uploadCommandsContainer.innerHTML = '<div class="alert alert-danger">Impossible de charger l\'historique.</div>';
                    emailCommandsContainer.innerHTML = '<div class="alert alert-danger">Le serveur est peut-être inaccessible.</div>';
                });
        };

        refreshBtn.addEventListener('click', fetchAdminData);

        deleteAllBtn.addEventListener('click', () => {
             if (confirm("ATTENTION !\n\nÊtes-vous sûr de vouloir effacer TOUT l'historique ?\n\nCETTE ACTION EST IRRÉVERSIBLE.")) {
                fetch('/api/delete_all_tasks', { method: 'POST' }).then(res => res.json()).then(data => {
                    if (data.success) fetchAdminData(); else alert(`Erreur: ${data.error}`);
                });
            }
        });

        function getPopoverContent(id, type) {
            const idAttribute = type === 'task' ? `data-task-id="${id}"` : `data-job-id="${id}"`;
            return `
                <div class="reprint-popover-body">
                    <div class="mb-2">
                        <label class="form-label">Couleur</label>
                        <div class="reprint-option-group">
                            <button type="button" class="option-btn active" data-name="is_color" data-value="false">N&B</button>
                            <button type="button" class="option-btn" data-name="is_color" data-value="true">Couleur</button>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Recto/Verso</label>
                        <div class="reprint-option-group">
                            <button type="button" class="option-btn active" data-name="is_duplex" data-value="false">Recto</button>
                            <button type="button" class="option-btn" data-name="is_duplex" data-value="true">R/V</button>
                        </div>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Copies</label>
                        <input type="number" class="form-control form-control-sm popover-copies-input" value="1" min="1">
                    </div>
                    <button class="btn btn-sm btn-dark w-100 reprint-popover-confirm-btn" ${idAttribute}>Valider</button>
                </div>`;
        }

        // On écoute les clics sur tout le panneau admin pour gérer les popovers
        adminPanel.addEventListener('click', (event) => {
            const reprintBtn = event.target.closest('.reprint-btn');
            const reprintJobBtn = event.target.closest('.reprint-job-btn');
            const deleteTaskBtn = event.target.closest('.delete-task-btn');

            let button = null;
            let type = '';
            let id = '';

            if (reprintBtn) { button = reprintBtn; type = 'task'; id = button.dataset.taskId; }
            if (reprintJobBtn) { button = reprintJobBtn; type = 'job'; id = button.dataset.jobId; }

            if (button) {
                event.preventDefault();
                if (currentPopover && currentPopover._element !== button) {
                    currentPopover.dispose();
                }
                currentPopover = new bootstrap.Popover(button, {
                    html: true,
                    sanitize: false,
                    content: getPopoverContent(id, type),
                    title: 'Options de réimpression',
                    placement: 'left'
                });
                currentPopover.show();
                return;
            }

            if (deleteTaskBtn) {
                if (currentPopover) currentPopover.dispose();
                const { taskId, filename } = deleteTaskBtn.dataset;
                if (confirm(`Supprimer la tâche pour "${filename}" ?`)) {
                    fetch(`/api/delete_task/${taskId}`, { method: 'POST' })
                        .then(res => res.json()).then(data => {
                            if (data.success) fetchAdminData(); else alert(`Erreur: ${data.error}`);
                        });
                }
            }
        });

        document.body.addEventListener('click', function(event) {
            const target = event.target;
            const confirmBtn = target.closest('.reprint-popover-confirm-btn');

            if (!target.closest('.popover') && currentPopover) {
                if (!currentPopover._element.contains(target)) {
                    currentPopover.dispose();
                    currentPopover = null;
                }
                return;
            }

            if (target.classList.contains('option-btn')) {
                const group = target.parentElement;
                group.querySelectorAll('.option-btn').forEach(btn => btn.classList.remove('active'));
                target.classList.add('active');
            }

            if (confirmBtn) {
                const popover = confirmBtn.closest('.popover');
                const options = {
                    copies: parseInt(popover.querySelector('.popover-copies-input').value) || 1,
                    is_color: popover.querySelector('.option-btn[data-name="is_color"].active').dataset.value === 'true',
                    is_duplex: popover.querySelector('.option-btn[data-name="is_duplex"].active').dataset.value === 'true'
                };

                let url, payload;
                const taskId = confirmBtn.dataset.taskId;
                const jobId = confirmBtn.dataset.jobId;

                if (taskId) {
                    url = '/reprint';
                    payload = { task_id: taskId, ...options };
                } else if (jobId) {
                    url = '/api/reprint_job';
                    payload = { job_id: jobId, options: options };
                } else {
                    return;
                }

                fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
                    .then(res => {
                        if (!res.ok) throw new Error(`Erreur serveur (${res.status})`);
                        return res.json();
                    })
                    .then(result => {
                        if (result.success) {
                            reprintToast.show();
                        } else {
                            alert(`Erreur: ${result.error || 'Une erreur est survenue.'}`);
                        }
                    })
                    .catch(err => alert(`Erreur de communication: ${err.message}`))
                    .finally(() => {
                        if (currentPopover) {
                            currentPopover.dispose();
                            currentPopover = null;
                        }
                    });
            }
        });

        document.addEventListener("visibilitychange", () => {
            if (document.hidden) clearInterval(refreshInterval);
            else { fetchAdminData(); refreshInterval = setInterval(fetchAdminData, 5000); }
        });

        fetchAdminData();
        refreshInterval = setInterval(fetchAdminData, 5000);
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
                    if (data.success) {
                        showAdminPanel();
                    } else {
                        loginError.textContent = data.error || "Une erreur est survenue.";
                        loginError.classList.remove('d-none');
                    }
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
