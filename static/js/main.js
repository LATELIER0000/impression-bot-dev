// static/js/main.js
document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('file-input');
    const addFileButton = document.getElementById('add-file-button');
    const fileListContainer = document.getElementById('file-list-container');
    const clientNameInput = document.getElementById('client_name');
    const summaryButton = document.getElementById('summary-button');
    const modalPrintForm = document.getElementById('modal-print-form');
    const fileOptionsArea = document.getElementById('file-options-area');
    const toastContainer = document.getElementById('toast-container');

    let fileStore = [];
    let currentJobId = null;
    let pollingInterval = null;

    function showToast(message, type = 'danger') {
        const toastId = `toast-${Date.now()}`;
        const toastHTML = `
            <div id="${toastId}" class="toast align-items-center text-bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true">
              <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
              </div>
            </div>`;
        toastContainer.innerHTML += toastHTML;
        const toastEl = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastEl);
        toast.show();
        toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
    }

    function formatBytes(bytes, d = 2) {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const s = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return `${parseFloat((bytes / Math.pow(k, i)).toFixed(d))} ${s[i]}`;
    }

    addFileButton.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', () => {
        if (!clientNameInput.value.trim()) {
            showToast("Veuillez d'abord renseigner votre nom.", "warning");
            fileInput.value = '';
            return;
        }
        clientNameInput.disabled = true;

        if (!currentJobId) {
            currentJobId = `job-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
        }

        const newFiles = Array.from(fileInput.files);
        fileInput.value = '';

        newFiles.forEach(file => {
            if (fileStore.some(f => f.file.name === file.name && f.file.size === file.size)) return;

            const taskId = `task-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
            const fileEntry = { id: taskId, file: file, status: 'queued', serverStatus: null, serverData: null, error: null };
            fileStore.push(fileEntry);
            addFileToListDOM(fileEntry, fileStore.length - 1);
        });

        startProcessingQueue();
        if (!pollingInterval) startPolling();
    });

    function addFileToListDOM(fileEntry, index) {
        fileOptionsArea.classList.remove('d-none');
        const template = document.getElementById('file-row-template');
        const file = fileEntry.file;
        const fileRow = template.content.cloneNode(true).querySelector('li');
        fileRow.dataset.taskId = fileEntry.id;

        fileRow.querySelector('.file-name-placeholder').textContent = file.name;
        fileRow.querySelector('.file-details-placeholder').innerHTML = `<i class="bi bi-file-earmark-binary"></i> ${file.type || 'Fichier'} <span class="mx-2">|</span> <i class="bi bi-hdd"></i> ${formatBytes(file.size)}`;

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
        const filesToUpload = fileStore.filter(f => f.status === 'queued');
        filesToUpload.forEach(fileEntry => {
            fileEntry.status = 'uploading';
            updateFileStatusUI(fileEntry.id, 'uploading');

            const formData = new FormData();
            formData.append('file', fileEntry.file);
            formData.append('client_name', clientNameInput.value);
            formData.append('job_id', currentJobId);
            formData.append('task_id', fileEntry.id);

            fetch('/upload_and_process_file', { method: 'POST', body: formData })
                .then(res => res.json())
                .then(data => {
                    if (!data.success) {
                        fileEntry.status = 'error';
                        fileEntry.error = data.error || 'Erreur serveur';
                        updateFileStatusUI(fileEntry.id, 'error', fileEntry.error);
                    }
                })
                .catch(err => {
                    fileEntry.status = 'error';
                    fileEntry.error = 'Erreur de connexion.';
                    updateFileStatusUI(fileEntry.id, 'error', fileEntry.error);
                });
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
                        if (fileEntry && fileEntry.serverStatus !== taskData.status) {
                            fileEntry.serverStatus = taskData.status;
                            fileEntry.serverData = taskData;
                            updateFileStatusUI(fileEntry.id, taskData.status, taskData);
                        }
                    });

                    updateSummaryButton();

                    if (data.is_complete) {
                        clearInterval(pollingInterval);
                        pollingInterval = null;
                    }
                })
                .catch(err => {
                    console.error("Erreur de polling:", err);
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                });
        }, 2500);
    }

    function updateSummaryButton() {
        if (fileStore.length === 0) {
            summaryButton.disabled = true;
            summaryButton.textContent = 'Suivant';
            return;
        }

        const finalStates = ['PRET_POUR_CALCUL', 'ERREUR_CONVERSION', 'ERREUR_PAGE_COUNT'];
        const isProcessing = fileStore.some(f => !f.serverStatus || !finalStates.includes(f.serverStatus));
        const hasReadyFiles = fileStore.some(f => f.serverStatus === 'PRET_POUR_CALCUL');

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

        const removeBtn = fileRow.querySelector('.remove-file-btn');
        const processingStates = ['uploading', 'EN_ATTENTE_TRAITEMENT', 'CONVERSION_EN_COURS', 'COMPTAGE_PAGES'];
        removeBtn.disabled = processingStates.includes(status);

        const statusDiv = fileRow.querySelector('.file-status');
        let statusHTML = '';
        switch(status) {
            case 'uploading': statusHTML = `<span class="text-primary"><span class="spinner-border spinner-border-sm me-2"></span>Envoi...</span>`; break;
            case 'EN_ATTENTE_TRAITEMENT':
            case 'CONVERSION_EN_COURS':
            case 'COMPTAGE_PAGES': statusHTML = `<span class="text-primary"><span class="spinner-border spinner-border-sm me-2"></span>Traitement...</span>`; break;
            case 'error':
            case 'ERREUR_CONVERSION':
            case 'ERREUR_PAGE_COUNT':
                const errorMsg = typeof data === 'string' ? data : (status.replace(/_/g, ' '));
                statusHTML = `<span class="text-danger">❌ ${errorMsg}</span>`; break;
            case 'PRET_POUR_CALCUL':
                statusHTML = `<span class="text-success">✅ Prêt</span>`; break;
            default: statusHTML = `<span class="text-muted">En attente...</span>`;
        }
        statusDiv.innerHTML = statusHTML;
    }

    fileListContainer.addEventListener('click', (e) => {
        const removeBtn = e.target.closest('.remove-file-btn');
        if (removeBtn && !removeBtn.disabled) {
            const liToRemove = removeBtn.closest('li');
            if (liToRemove) {
                const taskId = liToRemove.dataset.taskId;
                fileStore = fileStore.filter(f => f.id !== taskId);
                liToRemove.remove();

                updateSummaryButton();
                if (fileStore.length === 0) {
                    clientNameInput.disabled = false;
                    currentJobId = null;
                    fileOptionsArea.classList.add('d-none');
                }
            }
            return;
        }

        // CORRECTION: La logique est maintenant basée sur l'élément <li> parent au lieu d'un <form> inexistant.
        const optionBtn = e.target.closest('.option-btn');
        if (optionBtn) {
            const li = optionBtn.closest('li');
            const group = optionBtn.closest('.option-btn-group');
            const groupName = group.dataset.groupName;
            const value = optionBtn.dataset.value;

            li.querySelector(`input[name="${groupName}"]`).value = value;
            group.querySelectorAll('.option-btn').forEach(btn => btn.classList.remove('active'));
            optionBtn.classList.add('active');

            if (groupName === 'pagemode') {
                const rangeInputs = li.querySelector('.page-range-inputs');
                rangeInputs.classList.toggle('d-none', value !== 'range');
            }
        }
    });

    summaryButton.addEventListener('click', function() {
        const tasksPayload = fileStore
            .filter(f => f.serverStatus === 'PRET_POUR_CALCUL')
            .map(f => {
                // CORRECTION: On récupère les champs depuis le <li> de la tâche, sans utiliser FormData.
                const taskRow = fileListContainer.querySelector(`li[data-task-id="${f.id}"]`);
                const options = {};
                const inputs = taskRow.querySelectorAll('[name]');
                inputs.forEach(input => {
                    options[input.name] = input.value;
                });
                return { task_id: f.id, options: options };
            });

        if (tasksPayload.length === 0) {
            showToast("Aucun fichier n'est prêt à être imprimé.", "warning");
            return;
        }

        fetch('/calculate_summary', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job_id: currentJobId, tasks: tasksPayload })
        })
        .then(res => res.json())
        .then(data => {
            if (data.success && data.print_job_summary) {
                const hasFailedFiles = fileStore.some(f => f.serverStatus?.includes('ERREUR'));
                showConfirmationModal(data.print_job_summary, hasFailedFiles);
            } else {
                showToast(data.error || "Impossible de calculer le résumé.");
            }
        });
    });

    function showConfirmationModal(data, hasFailedFiles) {
        document.getElementById('modal-client-name').textContent = data.client_name;
        document.getElementById('modal-total-price').textContent = `${data.prix_total.toFixed(2)} €`;
        const taskList = document.getElementById('modal-task-list');
        taskList.innerHTML = '';

        if (hasFailedFiles) {
            const warningHTML = `<div class="alert alert-warning small"><i class="bi bi-exclamation-triangle-fill"></i> <strong>Attention :</strong> Certains fichiers n'ont pas pu être traités et n'apparaissent pas ci-dessous. Ils ne seront pas imprimés.</div>`;
            taskList.innerHTML += warningHTML;
        }

        data.tasks.forEach(task => {
            const colorIcon = task.is_color ? '<i class="bi bi-palette-fill" style="color: #0d6efd;"></i> Couleur' : '<i class="bi bi-palette text-secondary"></i> N&B';
            const duplexIcon = task.is_duplex ? '<i class="bi bi-layers-fill text-secondary"></i> Recto/Verso' : '<i class="bi bi-file-earmark-text text-secondary"></i> Recto';
            const taskHTML = `<div class="task-card"><div class="d-flex justify-content-between align-items-start"><h6 class="fw-bold file-name me-3">${task.name}</h6><span class="badge bg-primary rounded-pill fs-6">${task.prix.toFixed(2)} €</span></div><hr class="my-2"><div class="task-details text-muted"><div class="detail-item"><i class="bi bi-file-earmark-ruled text-secondary"></i> ${task.pages} page(s)</div><div class="detail-item"><i class="bi bi-files text-secondary"></i> ${task.copies} copie(s)</div><div class="detail-item">${colorIcon}</div><div class="detail-item">${duplexIcon}</div></div></div>`;
            taskList.innerHTML += taskHTML;
        });
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
            if (data.success) {
                window.location.href = '/?success_message=Impression+lancée+avec+succès+!';
            } else {
                showToast(data.error || "Une erreur s'est produite lors du lancement de l'impression.");
            }
        })
        .catch(err => {
            console.error(err);
            document.getElementById('loading-overlay').style.display = 'none';
            showToast("Erreur de communication avec le serveur.");
        });
    });

    const urlParams = new URLSearchParams(window.location.search);
    const successMessage = urlParams.get('success_message');
    const errorMessage = urlParams.get('error_message');
    if (successMessage) {
        showToast(successMessage, 'success');
        window.history.replaceState({}, document.title, "/");
    }
    if (errorMessage) {
        showToast(errorMessage, 'danger');
        window.history.replaceState({}, document.title, "/");
    }
});
