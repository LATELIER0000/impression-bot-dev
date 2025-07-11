// static/js/admin.js
document.addEventListener('DOMContentLoaded', function() {
    const loginSection = document.getElementById('login-section');
    const adminPanel = document.getElementById('admin-panel');
    const loginForm = document.getElementById('login-form');
    const loginError = document.getElementById('login-error');

    let refreshInterval;

    // --- Logique du Panneau Admin (sera initialisée après connexion) ---
    function initializeAdminPanel() {
        const refreshBtn = document.getElementById('refresh-btn');
        const deleteAllBtn = document.getElementById('delete-all-btn');
        const commandsContainer = document.getElementById('commands-container');
        const reprintToast = new bootstrap.Toast(document.getElementById('reprintToast'));

        const fetchAdminData = () => {
            const openCollapses = new Set();
            commandsContainer.querySelectorAll('.collapse.show').forEach(el => {
                openCollapses.add(el.id);
            });

            fetch('/api/admin_data')
                .then(res => res.ok ? res.json() : Promise.reject(res))
                .then(data => {
                    if (data.error) {
                        console.error('API Error:', data.error);
                        if (data.error === 'Non autorisé') window.location.reload();
                        return;
                    }
                    document.getElementById('total-revenue-display').textContent = `${data.total_revenue} €`;
                    document.getElementById('total-pages-display').textContent = data.total_pages;

                    commandsContainer.innerHTML = '';
                    if (!data.commands || data.commands.length === 0) {
                        commandsContainer.innerHTML = '<p class="text-center text-muted">Aucune commande dans l\'historique.</p>';
                        deleteAllBtn.disabled = true;
                        return;
                    }
                    deleteAllBtn.disabled = false;

                    data.commands.forEach((command, index) => {
                        const collapseId = `command-details-${index}`;
                        const isOpen = openCollapses.has(collapseId);
                        const showClass = isOpen ? 'show' : '';

                        let filesHTML = '';
                        command.files.forEach(file => {
                            let statusBadge = '';
                            const status = file.status || 'INCONNU';
                            if (status.includes('ERREUR')) statusBadge = `<span class="badge bg-danger">${status.replace(/_/g, ' ')}</span>`;
                            else if (status === 'IMPRIME_AVEC_SUCCES') statusBadge = `<span class="badge bg-success">Imprimé</span>`;
                            else if (status === 'IMPRESSION_EN_COURS') statusBadge = `<span class="badge bg-info text-dark">Impression...</span>`;
                            else statusBadge = `<span class="badge bg-secondary">${status.replace(/_/g, ' ')}</span>`;

                            const isColor = file.color === 'Couleur';
                            const isDuplex = file.duplex === 'Recto-Verso';
                            const priceDisplay = file.price ? `<small class="text-muted">(${parseFloat(file.price).toFixed(2)}€)</small>` : '';
                            const downloadLink = file.task_id ? `<a href="/download/${file.task_id}" target="_blank" class="text-decoration-none">${file.file_name}</a>` : file.file_name;

                            filesHTML += `
                                <li class="list-group-item d-flex justify-content-between align-items-center flex-wrap">
                                    <div class="me-auto" style="word-break: break-all; padding-right: 1rem;">
                                        ${downloadLink} ${priceDisplay}
                                        <div class="mt-1">${statusBadge}</div>
                                    </div>
                                    <div class="btn-group mt-1 mt-sm-0" role="group">
                                        <button class="btn btn-sm btn-outline-secondary reprint-btn" title="Réimprimer"
                                            data-task-id="${file.task_id}" data-is-color="${isColor}" data-is-duplex="${isDuplex}" data-paper-size="${file.paper_size}"
                                            ${status.includes('ERREUR') || !file.task_id ? 'disabled' : ''}>
                                            <i class="bi bi-printer"></i>
                                        </button>
                                        <button class="btn btn-sm btn-outline-danger delete-task-btn" title="Supprimer cette tâche"
                                            data-task-id="${file.task_id}"
                                            data-filename="${file.file_name}"
                                            ${!file.task_id ? 'disabled' : ''}>
                                            <i class="bi bi-x-lg"></i>
                                        </button>
                                    </div>
                                </li>`;
                        });
                        const cardStatusClass = command.job_status === 'error' ? 'status-error' : (command.job_status === 'pending' ? 'status-pending' : '');
                        const cardHTML = `
                            <div class="card shadow-sm mb-3 ${cardStatusClass}">
                                <div class="card-body">
                                    <a href="#" class="text-decoration-none text-dark" data-bs-toggle="collapse" data-bs-target="#${collapseId}">
                                        <div class="d-flex justify-content-between align-items-center">
                                            <div><h5 class="card-title mb-0">${command.client_name}</h5><small class="text-muted">${command.timestamp}</small></div>
                                            <div class="text-end"><strong class="fs-5">${command.total_price.toFixed(2)} €</strong><div class="small text-muted">${command.files.length} fichier(s) <i class="bi bi-chevron-down"></i></div></div>
                                        </div>
                                    </a>
                                    <div class="collapse ${showClass}" id="${collapseId}"><hr><ul class="list-group list-group-flush">${filesHTML}</ul></div>
                                </div>
                            </div>`;
                        commandsContainer.innerHTML += cardHTML;
                    });
                })
                .catch(error => {
                    console.error('Erreur lors de la récupération des données admin:', error);
                    commandsContainer.innerHTML = '<div class="alert alert-danger">Impossible de charger l\'historique.</div>';
                });
        };

        refreshBtn.addEventListener('click', fetchAdminData);
        deleteAllBtn.addEventListener('click', () => {
             if (confirm("ATTENTION !\n\nÊtes-vous absolument sûr de vouloir effacer TOUT l'historique des commandes ?\n\nCETTE ACTION EST DÉFINITIVE ET IRRÉVERSIBLE.")) {
                fetch('/api/delete_all_tasks', { method: 'POST' })
                    .then(res => res.json())
                    .then(data => {
                        if (data.success) {
                            fetchAdminData();
                        } else {
                            alert(`Erreur: ${data.error || "Impossible de vider l'historique."}`);
                        }
                    });
            }
        });

        commandsContainer.addEventListener('click', (event) => {
            const reprintButton = event.target.closest('.reprint-btn');
            const deleteTaskButton = event.target.closest('.delete-task-btn');

            if (reprintButton) {
                reprintButton.disabled = true;
                reprintButton.innerHTML = `<span class="spinner-border spinner-border-sm"></span>`;
                const data = { task_id: reprintButton.dataset.taskId, is_color: reprintButton.dataset.isColor === 'true', is_duplex: reprintButton.dataset.isDuplex === 'true', paper_size: reprintButton.dataset.paperSize || '2' };
                fetch('/reprint', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) })
                    .then(res => res.json()).then(result => {
                        if (result.success) {
                            reprintToast.show();
                        } else {
                            alert(`Erreur: ${result.error || "Erreur inconnue"}`);
                        }
                    });
                return;
            }

            if (deleteTaskButton) {
                const { taskId, filename } = deleteTaskButton.dataset;
                if (confirm(`Êtes-vous sûr de vouloir supprimer la tâche pour "${filename}" ?`)) {
                    fetch(`/api/delete_task/${taskId}`, { method: 'POST' })
                        .then(res => res.json()).then(data => {
                            if (data.success) {
                                fetchAdminData();
                            } else {
                                alert(`Erreur: ${data.error || "Impossible de supprimer la tâche."}`);
                            }
                        });
                }
            }
        });

        document.addEventListener("visibilitychange", () => {
            if (document.hidden) {
                clearInterval(refreshInterval);
            } else {
                fetchAdminData();
                refreshInterval = setInterval(fetchAdminData, 5000);
            }
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
