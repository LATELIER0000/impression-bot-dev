document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('file-input');
    const addFileButton = document.getElementById('add-file-button');
    const fileListContainer = document.getElementById('file-list-container');
    const clientNameInput = document.getElementById('client_name');
    const summaryButton = document.getElementById('summary-button');
    const modalPrintForm = document.getElementById('modal-print-form');
    const fileOptionsArea = document.getElementById('file-options-area');
    const toastContainer = document.getElementById('toast-container');

    const PRIX_NB = parseFloat(document.getElementById('prix-nb-display').textContent.replace(',', '.'));
    const PRIX_C = parseFloat(document.getElementById('prix-c-display').textContent.replace(',', '.'));

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

    function calculateTaskPrice(taskId) {
        const fileEntry = fileStore.find(f => f.id === taskId);
        const taskRow = fileListContainer.querySelector(`li[data-task-id="${taskId}"]`);
        if (!fileEntry || !taskRow) return;

        const pricePlaceholder = taskRow.querySelector('.task-price-placeholder');
        // MODIFIÉ: S'assurer que serverData existe avant de chercher les pages
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
            if (file.size === 0) {
                showToast(`Le fichier "${file.name}" est vide et ne peut pas être envoyé.`, 'danger');
                return;
            }
            const taskId = `task-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
            const fileEntry = { id: taskId, file: file, status: 'queued', serverStatus: null, serverData: null };
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
        fileRow.querySelector('.file-details-placeholder').innerHTML = `<i class="bi bi-file-earmark-binary"></i> ${file.type || 'Fichier'} | <i class="bi bi-hdd"></i> ${formatBytes(file.size)}`;

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
                .then(data => { if (!data.success) { fileEntry.status = 'error'; updateFileStatusUI(fileEntry.id, 'error', data.error || 'Erreur serveur'); }})
                .catch(err => { fileEntry.status = 'error'; updateFileStatusUI(fileEntry.id, 'error', 'Erreur de connexion.'); });
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
                        // MODIFIÉ: On met à jour même si le statut n'a pas changé, pour forcer la ré-évaluation de l'UI.
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

        // CORRECTION: On appelle la fonction de calcul de prix à chaque mise à jour de statut.
        // Si le fichier n'est pas prêt, la fonction mettra "--.-- €" ou "Prix à définir".
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
            case 'PRET_POUR_CALCUL': statusHTML = `<span class="text-success fw-bold">✅ Prêt</span>`; break;
            case 'PRET_SANS_COMPTAGE': statusHTML = `<span class="text-warning fw-bold">⚠️ Prêt (comptage manuel)</span>`; break;
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
                    clientNameInput.disabled = false;
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
        document.getElementById('modal-client-name').textContent = data.client_name;
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
            .catch(err => {
                console.error(err);
                document.getElementById('loading-overlay').style.display = 'none';
                showToast("Erreur de communication avec le serveur.");
            });
    });

    const urlParams = new URLSearchParams(window.location.search);
    const successMessage = urlParams.get('success_message');
    if (successMessage) {
        showToast(successMessage, 'success');
        window.history.replaceState({}, document.title, "/");
    }
});
