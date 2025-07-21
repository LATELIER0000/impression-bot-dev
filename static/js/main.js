document.addEventListener('DOMContentLoaded', function() {
    // On vérifie quelle partie de l'interface est affichée
    const userLoginForm = document.getElementById('user-login-form');
    const userMainSection = document.getElementById('user-main-section');

    // --- LOGIQUE POUR L'UTILISATEUR DÉCONNECTÉ ---
    // Ce bloc ne s'exécute que si le formulaire de connexion est présent sur la page.
    if (userLoginForm) {
        userLoginForm.addEventListener('submit', function(event) {
            event.preventDefault();
            const formData = new FormData(userLoginForm);
            const errorDiv = document.getElementById('user-login-error');
            fetch('/user_login', { method: 'POST', body: formData })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        window.location.reload();
                    } else {
                        errorDiv.textContent = data.error || "Une erreur est survenue.";
                        errorDiv.classList.remove('d-none');
                    }
                })
                .catch(() => {
                    errorDiv.textContent = "Erreur de connexion avec le serveur.";
                    errorDiv.classList.remove('d-none');
                });
        });
    }
    // --- LOGIQUE POUR L'UTILISATEUR CONNECTÉ ---
    // Ce bloc ne s'exécute que si l'interface principale de l'utilisateur est présente.
    else if (userMainSection) {
        const fileInput = document.getElementById('file-input');
        const addFileButton = document.getElementById('add-file-button');
        const fileListContainer = document.getElementById('file-list-container');
        const summaryButton = document.getElementById('summary-button');
        const modalPrintForm = document.getElementById('modal-print-form');
        const fileOptionsArea = document.getElementById('file-options-area');
        const toastContainer = document.getElementById('toast-container');
        const historyTab = document.getElementById('history-tab');
        const newPrintTab = document.getElementById('new-print-tab');
        const userHistoryContainer = document.getElementById('user-history-container');

        const PRIX_NB = parseFloat(document.getElementById('prix-nb-display').textContent.replace(',', '.'));
        const PRIX_C = parseFloat(document.getElementById('prix-c-display').textContent.replace(',', '.'));
        const ALLOWED_EXTENSIONS = ['pdf', 'png', 'jpg', 'jpeg', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'txt'];

        let fileStore = [];
        let currentJobId = null;
        let pollingInterval = null;
        let currentUserPopover = null;
        let historyPollingInterval = null;

        function showToast(message, type = 'danger') {
            const toastId = `toast-${Date.now()}`;
            const toastHTML = `<div id="${toastId}" class="toast align-items-center text-bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true"><div class="d-flex"><div class="toast-body">${message}</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button></div></div>`;
            toastContainer.insertAdjacentHTML('beforeend', toastHTML);
            const toastEl = document.getElementById(toastId);
            const toast = new bootstrap.Toast(toastEl);
            toast.show();
            toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
        }

        function formatBytes(bytes, d = 2) {
            if (!bytes || bytes === 0) return '0 B';
            const k = 1024; const s = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return `${parseFloat((bytes / Math.pow(k, i)).toFixed(d))} ${s[i]}`;
        }

        function calculateTaskPrice(taskId) {
            const fileEntry = fileStore.find(f => f.id === taskId);
            const taskRow = fileListContainer.querySelector(`li[data-task-id="${taskId}"]`);
            if (!fileEntry || !taskRow) return;

            const pricePlaceholder = taskRow.querySelector('.task-price-placeholder');
            const pages = fileEntry.serverData ? (fileEntry.serverData.pages || 0) : 0;

            if (pages === 0) {
                pricePlaceholder.textContent = 'Prix à définir';
                return;
            }

            const copies = parseInt(taskRow.querySelector('input[name="copies"]').value) || 1;
            const isColor = taskRow.querySelector('input[name="color"]').value === 'color';
            const pageMode = taskRow.querySelector('input[name="pagemode"]').value;
            const startPage = parseInt(taskRow.querySelector('input[name="startpage"]').value);
            const endPage = parseInt(taskRow.querySelector('input[name="endpage"]').value);

            let pagesToPrint = pages;
            if (pageMode === 'range' && startPage > 0 && endPage >= startPage) {
                pagesToPrint = (endPage - startPage) + 1;
            }

            const pricePerPage = isColor ? PRIX_C : PRIX_NB;
            const totalPrice = pagesToPrint * copies * pricePerPage;

            pricePlaceholder.textContent = `${totalPrice.toFixed(2)} €`;
        }

        addFileButton.addEventListener('click', () => fileInput.click());

        fileInput.addEventListener('change', () => {
            if (!currentJobId) {
                currentJobId = `job-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
            }
            Array.from(fileInput.files).forEach(file => {
                const extension = file.name.split('.').pop().toLowerCase();
                if (!ALLOWED_EXTENSIONS.includes(extension)) {
                    showToast(`Le type de fichier "${file.name}" (.${extension}) n'est pas supporté.`, 'danger'); return;
                }
                if (fileStore.some(f => f.file.name === file.name && f.file.size === file.size)) return;
                if (file.size === 0) { showToast(`Le fichier "${file.name}" est vide.`, 'danger'); return; }
                const taskId = `task-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
                const fileEntry = { id: taskId, file: file, status: 'queued', serverStatus: null, serverData: null };
                fileStore.push(fileEntry);
                addFileToListDOM(fileEntry, fileStore.length - 1);
            });
            fileInput.value = '';
            startProcessingQueue();
            if (!pollingInterval && fileStore.length > 0) startPolling();
        });

        function addFileToListDOM(fileEntry, index) {
            fileOptionsArea.classList.remove('d-none');
            const template = document.getElementById('file-row-template');
            const file = fileEntry.file;
            const fileRow = template.content.cloneNode(true).querySelector('li');
            fileRow.dataset.taskId = fileEntry.id;
            fileRow.querySelector('.file-name-placeholder').textContent = file.name;

            // MODIFIÉ : Affiche l'extension du fichier au lieu du type MIME complet.
            const fileExtension = (file.name.split('.').pop() || 'INCONNU').toUpperCase();
            fileRow.querySelector('.file-details-placeholder').innerHTML = `<i class="bi bi-file-earmark-binary"></i> ${fileExtension} | <i class="bi bi-hdd"></i> ${formatBytes(file.size)}`;

            const collapseLink = fileRow.querySelector('[data-bs-toggle="collapse"]');
            const collapseTarget = fileRow.querySelector('.collapse');
            if (collapseLink && collapseTarget) {
                const collapseId = `advanced-options-${index}`;
                collapseLink.href = `#${collapseId}`;
                collapseTarget.id = collapseId;
            }
            fileListContainer.appendChild(fileRow);
        }

        function startProcessingQueue() {
            fileStore.filter(f => f.status === 'queued').forEach(fileEntry => {
                fileEntry.status = 'uploading';
                updateFileStatusUI(fileEntry.id, 'uploading');
                const formData = new FormData();
                formData.append('file', fileEntry.file);
                formData.append('job_id', currentJobId);
                formData.append('task_id', fileEntry.id);
                fetch('/upload_and_process_file', { method: 'POST', body: formData })
                    .then(res => {
                        if (res.status === 401) { window.location.reload(); return; }
                        return res.json();
                    })
                    .then(data => { if (!data || !data.success) { fileEntry.status = 'error'; updateFileStatusUI(fileEntry.id, 'error', data.error || 'Erreur serveur'); }})
                    .catch(() => { fileEntry.status = 'error'; updateFileStatusUI(fileEntry.id, 'error', 'Erreur de connexion.'); });
            });
        }

        function startPolling() {
            if (pollingInterval) clearInterval(pollingInterval);
            pollingInterval = setInterval(() => {
                if (!currentJobId || fileStore.length === 0) {
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    updateSummaryButton();
                    return;
                }
                fetch(`/get_job_status/${currentJobId}`)
                    .then(res => res.json())
                    .then(data => {
                        if (!data || !data.tasks) return;
                        data.tasks.forEach(taskData => {
                            const fileEntry = fileStore.find(f => f.id === taskData.task_id);
                            if (fileEntry) {
                                fileEntry.serverStatus = taskData.status;
                                fileEntry.serverData = taskData;
                                updateFileStatusUI(fileEntry.id, taskData.status, taskData);
                            }
                        });
                        updateSummaryButton();
                        if (data.is_complete) { clearInterval(pollingInterval); pollingInterval = null; }
                    })
                    .catch(err => { console.error("Erreur de polling:", err); clearInterval(pollingInterval); pollingInterval = null; });
            }, 2500);
        }

        function updateSummaryButton() {
            if (fileStore.length === 0) {
                summaryButton.disabled = true;
                summaryButton.textContent = 'Suivant';
                return;
            }
            const finalStates = ['PRET_POUR_CALCUL', 'PRET_SANS_COMPTAGE', 'ERREUR_CONVERSION', 'ERREUR_PAGE_COUNT', 'ERREUR_FICHIER_VIDE', 'ERREUR_LECTURE_FATALE'];
            const isProcessing = fileStore.some(f => !f.serverStatus || !finalStates.includes(f.serverStatus));
            const hasReadyFiles = fileStore.some(f => f.serverStatus === 'PRET_POUR_CALCUL' || f.serverStatus === 'PRET_SANS_COMPTAGE');
            if (isProcessing) {
                summaryButton.disabled = true;
                summaryButton.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Traitement...`;
            } else if (hasReadyFiles) {
                summaryButton.disabled = false;
                summaryButton.textContent = 'Calculer le total';
            } else {
                summaryButton.disabled = true;
                summaryButton.textContent = 'Aucun fichier valide';
            }
        }

        function updateFileStatusUI(taskId, status, data) {
            const fileRow = document.querySelector(`li[data-task-id="${taskId}"]`);
            if (!fileRow) return;
            const optionsContainer = fileRow.querySelector('.options-container');
            const isReady = status === 'PRET_POUR_CALCUL' || status === 'PRET_SANS_COMPTAGE';
            optionsContainer.classList.toggle('d-none', !isReady);
            calculateTaskPrice(taskId);
            const removeBtn = fileRow.querySelector('.remove-file-btn');
            const processingStates = ['uploading', 'EN_ATTENTE_TRAITEMENT', 'CONVERSION_EN_COURS', 'COMPTAGE_PAGES'];
            removeBtn.disabled = processingStates.includes(status);
            const statusDiv = fileRow.querySelector('.file-status');
            let statusHTML = '';
            switch (status) {
                case 'uploading': case 'EN_ATTENTE_TRAITEMENT': case 'CONVERSION_EN_COURS': case 'COMPTAGE_PAGES':
                    statusHTML = `<span class="text-primary"><span class="spinner-border spinner-border-sm me-2"></span>Traitement...</span>`; break;
                case 'ERREUR_CONVERSION': statusHTML = `<span class="text-danger fw-bold">❌ Fichier non supporté</span>`; break;
                case 'ERREUR_FICHIER_VIDE': statusHTML = `<span class="text-danger fw-bold">❌ Fichier vide</span>`; break;
                case 'ERREUR_LECTURE_FATALE': statusHTML = `<span class="text-danger fw-bold">❌ Fichier corrompu</span>`; break;
                case 'PRET_POUR_CALCUL':
                    statusHTML = `<span class="text-success fw-bold">✅ Prêt</span> <a href="/preview/${taskId}" target="_blank" class="btn btn-outline-secondary btn-sm ms-2 py-0"><i class="bi bi-eye"></i> Aperçu</a>`; break;
                case 'PRET_SANS_COMPTAGE':
                    statusHTML = `<span class="text-warning fw-bold">⚠️ Prêt</span> <a href="/preview/${taskId}" target="_blank" class="btn btn-outline-secondary btn-sm ms-2 py-0"><i class="bi bi-eye"></i> Aperçu</a>`; break;
                default: statusHTML = `<span class="text-muted">En attente...</span>`;
            }
            statusDiv.innerHTML = statusHTML;
        }

        fileListContainer.addEventListener('change', (e) => {
            if (e.target.matches('input[name="copies"], input[name="startpage"], input[name="endpage"], select[name="papersize"]')) {
                const taskId = e.target.closest('li').dataset.taskId;
                calculateTaskPrice(taskId);
            }
        });

        fileListContainer.addEventListener('click', (e) => {
            const removeBtn = e.target.closest('.remove-file-btn');
            if (removeBtn && !removeBtn.disabled) {
                const liToRemove = removeBtn.closest('li');
                if (liToRemove) {
                    const taskId = liToRemove.dataset.taskId;
                    fileStore = fileStore.filter(f => f.id !== taskId);
                    liToRemove.remove();
                    if (fileStore.length === 0) {
                        currentJobId = null;
                        fileOptionsArea.classList.add('d-none');
                    }
                }
                return;
            }
            const optionBtn = e.target.closest('.option-btn');
            if (optionBtn) {
                const li = optionBtn.closest('li');
                const taskId = li.dataset.taskId;
                const group = optionBtn.closest('.option-btn-group');
                const groupName = group.dataset.groupName;
                const value = optionBtn.dataset.value;
                li.querySelector(`input[name="${groupName}"]`).value = value;
                group.querySelectorAll('.option-btn').forEach(btn => btn.classList.remove('active'));
                optionBtn.classList.add('active');
                if (groupName === 'pagemode') {
                    li.querySelector('.page-range-inputs').classList.toggle('d-none', value !== 'range');
                }
                calculateTaskPrice(taskId);
            }
        });

        summaryButton.addEventListener('click', function() {
            const tasksPayload = fileStore
                .filter(f => f.serverStatus === 'PRET_POUR_CALCUL' || f.serverStatus === 'PRET_SANS_COMPTAGE')
                .map(f => {
                    const taskRow = fileListContainer.querySelector(`li[data-task-id="${f.id}"]`);
                    const options = {};
                    taskRow.querySelectorAll('[name]').forEach(input => { options[input.name] = input.value; });
                    return { task_id: f.id, options: options };
                });
            if (tasksPayload.length === 0) { showToast("Aucun fichier n'est prêt à être imprimé.", "warning"); return; }
            fetch('/calculate_summary', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_id: currentJobId, tasks: tasksPayload }) })
                .then(res => res.json())
                .then(data => {
                    if (data.success && data.print_job_summary) {
                        const hasFailedFiles = fileStore.some(f => f.serverStatus?.includes('ERREUR'));
                        showConfirmationModal(data.print_job_summary, hasFailedFiles);
                    } else { showToast(data.error || "Impossible de calculer le résumé."); }
                });
        });

        function showConfirmationModal(data, hasFailedFiles) {
            document.getElementById('modal-client-name').textContent = data.username;
            const taskList = document.getElementById('modal-task-list');
            taskList.innerHTML = '';
            if (hasFailedFiles) {
                taskList.innerHTML += `<div class="alert alert-warning small"><i class="bi bi-exclamation-triangle-fill"></i> <strong>Attention :</strong> Certains fichiers n'ont pas pu être traités.</div>`;
            }
            let manualPriceTasksExist = false;
            data.tasks.forEach(task => {
                const colorIcon = task.is_color ? '<i class="bi bi-palette-fill text-primary"></i> Couleur' : '<i class="bi bi-palette text-secondary"></i> N&B';
                const duplexIcon = task.is_duplex ? '<i class="bi bi-layers-fill text-secondary"></i> R/V' : '<i class="bi bi-file-earmark-text text-secondary"></i> Recto';
                const pageInfo = task.pages > 0 ? `${task.pages} page(s)` : `<span class="text-warning">N/A</span>`;
                let priceBadge = `<span class="badge bg-primary rounded-pill fs-6">${task.prix.toFixed(2)} €</span>`;
                if (task.pages === 0) {
                    priceBadge = `<span class="badge bg-warning text-dark rounded-pill fs-6">Prix à définir</span>`;
                    manualPriceTasksExist = true;
                }
                const taskHTML = `<div class="task-card"><div class="d-flex justify-content-between align-items-start"><h6 class="fw-bold file-name me-3">${task.name}</h6>${priceBadge}</div><hr class="my-2"><div class="task-details text-muted"><div class="detail-item"><i class="bi bi-file-earmark-ruled text-secondary"></i> ${pageInfo}</div><div class="detail-item"><i class="bi bi-files text-secondary"></i> ${task.copies} copie(s)</div><div class="detail-item">${colorIcon}</div><div class="detail-item">${duplexIcon}</div></div></div>`;
                taskList.innerHTML += taskHTML;
            });
            let totalPriceDisplay = `${data.prix_total.toFixed(2)} €`;
            if (manualPriceTasksExist) {
                totalPriceDisplay += ` <span class="fs-6 text-warning">(+ tâches manuelles)</span>`;
            }
            document.getElementById('modal-total-price').innerHTML = totalPriceDisplay;
            new bootstrap.Modal(document.getElementById('confirmModal')).show();
        }

        modalPrintForm.addEventListener('submit', function(event) {
            event.preventDefault();
            const confirmModal = bootstrap.Modal.getInstance(document.getElementById('confirmModal'));
            if (confirmModal) confirmModal.hide();
            document.getElementById('loading-overlay').style.display = 'flex';
            fetch('/print', { method: 'POST' })
                .then(res => res.json())
                .then(data => {
                    document.getElementById('loading-overlay').style.display = 'none';
                    if (data.success) { window.location.href = '/?success_message=Impression+lancée+avec+succès+!'; }
                    else { showToast(data.error || "Une erreur s'est produite."); }
                })
                .catch(() => {
                    document.getElementById('loading-overlay').style.display = 'none';
                    showToast("Erreur de communication avec le serveur.");
                });
        });

        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('success_message')) {
            showToast(urlParams.get('success_message'), 'success');
            window.history.replaceState({}, document.title, "/");
        }

        function fetchUserHistory() {
            const scrollPosition = userHistoryContainer.scrollTop;

            fetch('/api/user_history')
                .then(res => {
                    if (res.status === 401) { window.location.reload(); return; }
                    return res.json();
                })
                .then(data => {
                    if (data.error) throw new Error(data.error);
                    if (data.length === 0) {
                        userHistoryContainer.innerHTML = '<p class="text-center text-muted p-4">Vous n\'avez pas encore de commande.</p>';
                        return;
                    }
                    userHistoryContainer.innerHTML = data.map(createHistoryCardHTML).join('');
                    userHistoryContainer.scrollTop = scrollPosition;
                })
                .catch(error => {
                    console.error("Erreur de chargement de l'historique:", error);
                    if(historyPollingInterval) clearInterval(historyPollingInterval);
                    userHistoryContainer.innerHTML = '<div class="alert alert-danger">Impossible de charger votre historique.</div>';
                });
        }

        function createHistoryCardHTML(command) {
            const filesHTML = command.files.map(file => {
                const isPrinted = file.status && file.status.includes('IMPRIME');
                const statusText = isPrinted ? 'Imprimé' : (file.status || 'Inconnu').replace(/_/g, ' ');
                const statusBadge = `<span class="badge ${isPrinted ? 'bg-success' : 'bg-secondary'}">${statusText}</span>`;

                const isPrintable = !file.status.includes('ERREUR');
                const priceDisplay = file.price ? `<small class="text-muted">(${(+file.price).toFixed(2)}€)</small>` : '';
                const fileNameHTML = isPrintable
                    ? `<a href="/download/${file.task_id}" target="_blank" class="text-decoration-none text-dark">${file.file_name}</a>`
                    : file.file_name;

                const reprintButtonHTML = `<button class="btn btn-sm btn-outline-dark user-reprint-btn" title="Réimprimer ce fichier" data-task-id="${file.task_id}" ${!isPrintable ? 'disabled' : ''}><i class="bi bi-printer"></i></button>`;

                return `<li class="list-group-item d-flex justify-content-between align-items-center flex-nowrap">
                            <div class="me-auto" style="word-break: break-all; padding-right: 1rem;">
                                ${fileNameHTML} ${priceDisplay}
                                <div class="mt-1">${statusBadge}</div>
                            </div>
                            <div class="btn-group" role="group">
                                ${reprintButtonHTML}
                            </div>
                        </li>`;
            }).join('');
            const sourceIcon = command.source === 'email' ? '<i class="bi bi-envelope-at-fill" title="Source: Email"></i>' : '<i class="bi bi-upload" title="Source: Upload"></i>';
            return `
                <div class="card mb-3">
                    <div class="card-body">
                        <div class="d-flex justify-content-between">
                            <div>
                                <h6 class="card-title mb-1">${sourceIcon} Commande du ${new Date(command.timestamp).toLocaleDateString('fr-FR')}</h6>
                                <small class="text-muted">${command.job_id}</small>
                            </div>
                            <strong class="fs-5">${command.total_price.toFixed(2)} €</strong>
                        </div>
                        <hr>
                        <ul class="list-group list-group-flush">${filesHTML}</ul>
                    </div>
                </div>`;
        }

        function getReprintPopoverContent(taskId) {
            return `<div class="reprint-popover-body p-2" style="font-size: 0.9rem;">
                        <div class="mb-2">
                            <label class="form-label small fw-bold">Couleur</label>
                            <div class="d-flex gap-2"><button type="button" class="btn btn-sm btn-outline-dark w-100 active" data-name="is_color" data-value="false">N&B</button><button type="button" class="btn btn-sm btn-outline-dark w-100" data-name="is_color" data-value="true">Couleur</button></div>
                        </div>
                        <div class="mb-3">
                            <label class="form-label small fw-bold">Recto/Verso</label>
                            <div class="d-flex gap-2"><button type="button" class="btn btn-sm btn-outline-dark w-100 active" data-name="is_duplex" data-value="false">Recto</button><button type="button" class="btn btn-sm btn-outline-dark w-100" data-name="is_duplex" data-value="true">R/V</button></div>
                        </div>
                        <div class="mb-3 d-flex align-items-center gap-2">
                            <label class="form-label small fw-bold mb-0">Copies</label>
                            <input type="number" class="form-control form-control-sm" data-name="copies" value="1" min="1" style="width: 70px;">
                        </div>
                        <button class="btn btn-sm btn-dark w-100 reprint-popover-confirm-btn" data-task-id="${taskId}">Valider & Imprimer</button>
                    </div>`;
        }

        userHistoryContainer.addEventListener('click', (event) => {
            const reprintBtn = event.target.closest('.user-reprint-btn');
            if (reprintBtn) {
                event.preventDefault();
                const taskId = reprintBtn.dataset.taskId;
                if (currentUserPopover && currentUserPopover._element !== reprintBtn) {
                    currentUserPopover.dispose();
                }
                currentUserPopover = new bootstrap.Popover(reprintBtn, {
                    html: true,
                    sanitize: false,
                    content: getReprintPopoverContent(taskId),
                    title: 'Options de réimpression',
                });
                currentUserPopover.show();
            }
        });

        document.body.addEventListener('click', function(event) {
            const target = event.target;

            if (!target.closest('.popover') && currentUserPopover) {
                if (!currentUserPopover._element.contains(target)) {
                    currentUserPopover.dispose();
                    currentUserPopover = null;
                }
                return;
            }

            if (target.matches('.popover .btn-outline-dark[data-name]')) {
                const group = target.parentElement;
                group.querySelectorAll('.btn').forEach(btn => btn.classList.remove('active'));
                target.classList.add('active');
            }

            const confirmBtn = target.closest('.reprint-popover-confirm-btn');
            if (confirmBtn) {
                const popoverEl = confirmBtn.closest('.popover');
                const payload = {
                    task_id: confirmBtn.dataset.taskId,
                    copies: parseInt(popoverEl.querySelector('[data-name="copies"]').value) || 1,
                    is_color: popoverEl.querySelector('.btn[data-name="is_color"].active').dataset.value === 'true',
                    is_duplex: popoverEl.querySelector('.btn[data-name="is_duplex"].active').dataset.value === 'true'
                };

                fetch('/api/user_reprint', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                })
                .then(res => res.json())
                .then(result => {
                    if (result.success) {
                        showToast('Réimpression lancée avec succès !', 'success');
                    } else {
                        showToast(result.error || 'Une erreur est survenue.', 'danger');
                    }
                })
                .catch(err => showToast(`Erreur de communication: ${err.message}`, 'danger'))
                .finally(() => {
                    if (currentUserPopover) {
                        currentUserPopover.dispose();
                        currentUserPopover = null;
                    }
                });
            }
        });

        if (historyTab) {
            historyTab.addEventListener('shown.bs.tab', () => {
                if(userHistoryContainer.innerHTML.trim() === '') {
                    userHistoryContainer.innerHTML = '<div class="text-center p-4"><div class="spinner-border spinner-border-sm"></div> Chargement de l\'historique...</div>';
                }
                fetchUserHistory();
                if (historyPollingInterval) clearInterval(historyPollingInterval);
                historyPollingInterval = setInterval(fetchUserHistory, 5000);
            });
        }

        if (newPrintTab) {
            newPrintTab.addEventListener('shown.bs.tab', () => {
                if (historyPollingInterval) {
                    clearInterval(historyPollingInterval);
                    historyPollingInterval = null;
                }
            });
        }
    }
});
