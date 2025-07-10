document.addEventListener('DOMContentLoaded', function() {
    const fileInput = document.getElementById('file-input');
    const addFileButton = document.getElementById('add-file-button');
    const fileListContainer = document.getElementById('file-list-container');
    const form = document.getElementById('print-form');
    let fileStore = [];

    function formatBytes(bytes, d = 2) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const s = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return `${parseFloat((bytes / Math.pow(k, i)).toFixed(d))} ${s[i]}`;
    }

    addFileButton.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', () => {
        for (const f of fileInput.files) {
            if (!fileStore.some(sf => sf.name === f.name && sf.size === f.size)) {
                fileStore.push(f);
            }
        }
        fileInput.value = '';
        renderFileList();
    });

    function renderFileList() {
        fileListContainer.innerHTML = '';
        const fileOptionsArea = document.getElementById('file-options-area');
        if (fileStore.length === 0) {
            fileOptionsArea.classList.add('d-none');
            return;
        }
        fileOptionsArea.classList.remove('d-none');
        fileStore.forEach((file, index) => {
            const fileRow = document.createElement('li');
            fileRow.className = `list-group-item ${index % 2 === 0 ? 'list-group-item-light' : ''} p-3`;
            const fileType = file.type.includes('pdf') ? 'PDF' : 'Image';
            fileRow.innerHTML = `
                <div class="d-flex justify-content-between align-items-start">
                    <div class="me-3 file-info-container"><h6 class="fw-bold mb-1">${file.name}</h6><small class="text-muted"><i class="bi bi-file-earmark-binary"></i> ${fileType} <span class="mx-2">|</span> <i class="bi bi-hdd"></i> ${formatBytes(file.size)}</small></div>
                    <button type="button" class="btn-close" aria-label="Supprimer" data-index="${index}"></button>
                </div>
                <div class="border rounded p-2 mt-2 bg-white">
                    <div class="d-flex flex-column flex-sm-row justify-content-around align-items-center gap-3">
                        <div class="d-flex align-items-center gap-2"><label for="copies_${index}" class="form-label mb-0 small">Copies:</label><input type="number" name="copies_${index}" id="copies_${index}" class="form-control form-control-sm" value="1" min="1" style="width: 70px;"></div>
                        <div class="w-100"><input type="hidden" name="color_${index}" value="bw"><div class="option-btn-group" data-group-name="color_${index}"><button type="button" class="btn option-btn active" data-value="bw">N&B</button><button type="button" class="btn option-btn" data-value="color">Couleur</button></div></div>
                    </div>
                    <div class="mt-2 text-center"><a class="small text-decoration-none" data-bs-toggle="collapse" href="#advanced-options-${index}"><i class="bi bi-gear"></i> Options avancées</a></div>
                    <div class="collapse mt-2" id="advanced-options-${index}">
                        <div class="p-2 bg-light rounded">
                            <div class="mb-3"><label class="form-label small">Format du Papier</label><select name="papersize_${index}" class="form-select form-select-sm"><option value="2" selected>A4</option><option value="1">A3</option><option value="3">A5</option></select></div>
                            <div class="mb-3"><label class="form-label small">Impression</label><input type="hidden" name="siding_${index}" value="recto"><div class="option-btn-group" data-group-name="siding_${index}"><button type="button" class="btn option-btn active" data-value="recto">Recto</button><button type="button" class="btn option-btn" data-value="recto_verso">R/V</button></div></div>
                            <div><label class="form-label small">Plage d'impression</label><input type="hidden" name="pagemode_${index}" value="all"><div class="option-btn-group" data-group-name="pagemode_${index}"><button type="button" class="btn option-btn active" data-value="all">Tout</button><button type="button" class="btn option-btn" data-value="range">Plage</button></div><div class="d-flex align-items-center gap-2 mt-2 page-range-inputs d-none"><input type="number" name="startpage_${index}" class="form-control form-control-sm" placeholder="Début" min="1"><span class="text-muted">-</span><input type="number" name="endpage_${index}" class="form-control form-control-sm" placeholder="Fin" min="1"></div></div>
                        </div>
                    </div>
                </div>`;
            fileListContainer.appendChild(fileRow);
        });
    }

    fileListContainer.addEventListener('click', (e) => {
        if (e.target.matches('.btn-close')) {
            fileStore.splice(parseInt(e.target.dataset.index), 1);
            renderFileList();
            return;
        }
        const optionBtn = e.target.closest('.option-btn');
        if (optionBtn) {
            const group = optionBtn.closest('.option-btn-group');
            const groupName = group.dataset.groupName;
            const value = optionBtn.dataset.value;
            document.querySelector(`input[name="${groupName}"]`).value = value;
            group.querySelectorAll('.option-btn').forEach(btn => btn.classList.remove('active'));
            optionBtn.classList.add('active');
            if (groupName.startsWith('pagemode')) {
                const rangeInputs = group.nextElementSibling;
                if (value === 'range') rangeInputs.classList.remove('d-none');
                else rangeInputs.classList.add('d-none');
            }
        }
    });

    form.addEventListener('submit', function(event) {
        event.preventDefault();
        if (!document.getElementById('client_name').value) {
            alert("Veuillez renseigner votre nom.");
            return;
        }
        if (fileStore.length === 0) {
            alert("Veuillez ajouter au moins un fichier.");
            return;
        }
        const submitButton = form.querySelector('button[type="submit"]');
        submitButton.disabled = true;
        submitButton.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Calcul...`;
        
        const formData = new FormData(form);
        fileStore.forEach(f => {
            // On retire l'ancien fichier s'il existe pour s'assurer qu'il n'y a pas de doublons
            if (formData.has('files[]')) {
                formData.delete('files[]');
            }
        });
        fileStore.forEach(f => formData.append('files[]', f));


        fetch('/calculate', {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.tasks) {
                    document.getElementById('modal-client-name').textContent = data.client_name;
                    document.getElementById('modal-total-price').textContent = `${data.prix_total.toFixed(2)} €`;
                    const taskList = document.getElementById('modal-task-list');
                    taskList.innerHTML = '';
                    data.tasks.forEach(task => {
                        const colorIcon = task.is_color ? '<i class="bi bi-palette-fill" style="color: #0d6efd;"></i> Couleur' : '<i class="bi bi-palette text-secondary"></i> N&B';
                        const duplexIcon = task.is_duplex ? '<i class="bi bi-layers-fill text-secondary"></i> Recto/Verso' : '<i class="bi bi-file-earmark-text text-secondary"></i> Recto';
                        const taskHTML = `<div class="task-card"><div class="d-flex justify-content-between align-items-start"><h6 class="fw-bold file-name me-3">${task.name}</h6><span class="badge bg-primary rounded-pill fs-6">${task.prix.toFixed(2)} €</span></div><hr class="my-2"><div class="task-details text-muted"><div class="detail-item"><i class="bi bi-file-earmark-ruled text-secondary"></i> ${task.pages} page(s)</div><div class="detail-item"><i class="bi bi-files text-secondary"></i> ${task.copies} copie(s)</div><div class="detail-item">${colorIcon}</div><div class="detail-item">${duplexIcon}</div></div></div>`;
                        taskList.innerHTML += taskHTML;
                    });
                    new bootstrap.Modal(document.getElementById('confirmModal')).show();
                } else {
                    alert(data.error || "Une erreur inconnue s'est produite.");
                }
            })
            .finally(() => {
                submitButton.disabled = false;
                submitButton.innerHTML = 'Calculer le Prix';
            });
    });
});