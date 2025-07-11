// static/js/main.js
document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('file-input');
    const addFileButton = document.getElementById('add-file-button');
    const fileListContainer = document.getElementById('file-list-container');
    const clientNameInput = document.getElementById('client_name');
    const summaryButton = document.getElementById('summary-button');
    const modalPrintForm = document.getElementById('modal-print-form');
    const confirmModalEl = document.getElementById('confirmModal');
    const fileOptionsArea = document.getElementById('file-options-area');

    let fileStore = [];
    let currentJobId = null;
    let pollingInterval = null;

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
            alert("Veuillez d'abord renseigner votre nom.");
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
            const fileEntry = {
                id: taskId,
                file: file,
                status: 'queued',
                serverStatus: null,
                serverData: null,
                error: null
            };
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

        fileRow.querySelector('.file-options-placeholder').innerHTML = `
            <form>
                <div class="d-flex flex-column flex-sm-row justify-content-around align-items-center gap-3">
                    <div class="d-flex align-items-center gap-2"><label class="form-label mb-0 small">Copies:</label><input type="number" name="copies" class="form-control form-control-sm" value="1" min="1" style="width: 70px;"></div>
                    <div class="w-100"><input type="hidden" name="color" value="bw"><div class="option-btn-group" data-group-name="color"><button type="button" class="btn option-btn active" data-value="bw">N&B</button><button type="button" class="btn option-btn" data-value="color">Couleur</button></div></div>
                </div>
                <div class="mt-2 text-center"><a class="small text-decoration-none" data-bs-toggle="collapse" href="#advanced-options-${index}"><i class="bi bi-gear"></i> Options avancées</a></div>
                <div class="collapse mt-2" id="advanced-options-${index}">
                    <div class="p-2 bg-light rounded">
                        <div class="mb-3"><label class="form-label small">Format</label><select name="papersize" class="form-select form-select-sm"><option value="2" selected>A4</option><option value="1">A3</option><option value="3">A5</option></select></div>
                        <div class="mb-3"><label class="form-label small">Impression</label><input type="hidden" name="siding" value="recto"><div class="option-btn-group" data-group-name="siding"><button type="button" class="btn option-btn active" data-value="recto">Recto</button><button type="button" class="btn option-btn" data-value="recto_verso">R/V</button></div></div>
                        <div><label class="form-label small">Plage</label><input type="hidden" name="pagemode" value="all"><div class="option-btn-group" data-group-name="pagemode"><button type="button" class="btn option-btn active" data-value="all">Tout</button><button type="button" class="btn option-btn" data-value="range">Plage</button></div><div class="d-flex align-items-center gap-2 mt-2 page-range-inputs d-none"><input type="number" name="startpage" class="form-control form-control-sm" placeholder="Début" min="1"><span class="text-muted">-</span><input type="number" name="endpage" class="form-control form-control-sm" placeholder="Fin" min="1"></div></div>
                    </div>
                </div>
            </form>`;

        fileListContainer.appendChild(fileRow);
    }

    function startProcessingQueue() {
        const filesToUpload = fileStore.filter(f => f.status === 'queued');
        filesToUpload.forEach(fileEntry => {
            fileEntry.status = 'uploading';
            updateFileStatusUI(fileEntry.id, 'uploading');

            const fileRow = fileListContainer.querySelector(`li[data-task-id="${fileEntry.id}"]`);
            const formData = new FormData(fileRow.querySelector('form'));
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
            summaryButton.textContent = 'Suivant'; // Texte par défaut
            return;
        }

        const finalStates = ['PRET_POUR_CALCUL', 'ERREUR_CONVERSION', 'ERREUR_PAGE_COUNT'];
        const isProcessing = fileStore.some(f => !f.serverStatus || !finalStates.includes(f.serverStatus));
        const hasReadyFiles = fileStore.some(f => f.serverStatus === 'PRET_POUR_CALCUL');

        if (isProcessing) {
            summaryButton.disabled = true;
            summaryButton.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Traitement en cours...`;
        } else if (hasReadyFiles) {
            summaryButton.disabled = false;
            summaryButton.textContent = 'Suivant'; // CORRECTION: Texte changé
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
                const errorMsg = typeof data === 'string' ? data : status.replace(/_/g, ' ');
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

        const optionBtn = e.target.closest('.option-btn');
        if (optionBtn) {
            const form = optionBtn.closest('form');
            const group = optionBtn.closest('.option-btn-group');
            const groupName = group.dataset.groupName;
            const value = optionBtn.dataset.value;
            form.querySelector(`input[name="${groupName}"]`).value = value;
            group.querySelectorAll('.option-btn').forEach(btn => btn.classList.remove('active'));
            optionBtn.classList.add('active');
            if (groupName === 'pagemode') {
                const rangeInputs = group.nextElementSibling;
                if (value === 'range') rangeInputs.classList.remove('d-none');
                else rangeInputs.classList.add('d-none');
            }
        }
    });

    summaryButton.addEventListener('click', function() {
        const tasksPayload = fileStore
            .filter(f => f.serverStatus === 'PRET_POUR_CALCUL')
            .map(f => {
                const formElement = fileListContainer.querySelector(`li[data-task-id="${f.id}"] form`);
                const formData = new FormData(formElement);
                const options = Object.fromEntries(formData.entries());
                return { task_id: f.id, options: options };
            });

        if (tasksPayload.length === 0) {
            alert("Aucun fichier n'est prêt à être imprimé.");
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
                alert(data.error || "Impossible de calculer le résumé.");
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
            if (data.success) {
                setTimeout(() => { window.location.href = '/?success_message=Impression+lancée+avec+succès+!'; }, 3000);
            } else {
                document.getElementById('loading-overlay').style.display = 'none';
                alert(data.error || "Une erreur s'est produite lors du lancement de l'impression.");
            }
        })
        .catch(err => {
            console.error(err);
            document.getElementById('loading-overlay').style.display = 'none';
            alert("Erreur de communication avec le serveur.");
        });
    });
});
