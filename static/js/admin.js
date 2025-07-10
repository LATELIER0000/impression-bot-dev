document.addEventListener('DOMContentLoaded', function() {
    const loginSection = document.getElementById('login-section');
    const adminPanel = document.getElementById('admin-panel');
    const loginForm = document.getElementById('login-form');
    const loginError = document.getElementById('login-error');
    const refreshBtn = document.getElementById('refresh-btn');
    let refreshInterval;

    const fetchAdminData = () => {
        fetch('/api/admin_data')
            .then(res => res.json())
            .then(data => {
                if (data.error) {
                    console.error('API Error:', data.error);
                    return;
                }
                document.getElementById('total-revenue-display').textContent = `${data.total_revenue} €`;
                document.getElementById('total-pages-display').textContent = data.total_pages;

                const container = document.getElementById('commands-container');
                container.innerHTML = '';
                if (!data.commands || data.commands.length === 0) {
                    container.innerHTML = '<p class="text-center text-muted">Aucune commande dans l\'historique.</p>';
                    return;
                }

                data.commands.forEach((command, index) => {
                    const collapseId = `command-details-${index}`;

                    let filesHTML = '';
                    command.files.forEach(file => {
                        const isColor = file.color === 'Couleur';
                        const isDuplex = file.duplex === 'Recto-Verso';
                        filesHTML += `
                            <li class="list-group-item d-flex justify-content-between align-items-center flex-wrap">
                                <div class="me-3"><a href="/download/${file.file_name}" target="_blank" class="text-decoration-none">${file.file_name}</a> <small class="text-muted">(${parseFloat(file.price).toFixed(2)}€)</small></div>
                                <button class="btn btn-sm btn-outline-secondary reprint-btn mt-1 mt-sm-0" data-filename="${file.file_name}" data-client="${file.client_name}" data-is-color="${isColor}" data-is-duplex="${isDuplex}">
                                    <span class="spinner-border spinner-border-sm d-none"></span><span class="button-text">Réimprimer</span>
                                </button>
                            </li>
                        `;
                    });

                    const cardHTML = `
                        <div class="card shadow-sm mb-3">
                            <div class="card-body">
                                <a href="#" class="text-decoration-none text-dark" data-bs-toggle="collapse" data-bs-target="#${collapseId}">
                                    <div class="d-flex justify-content-between align-items-center">
                                        <div>
                                            <h5 class="card-title mb-0">${command.client_name}</h5>
                                            <small class="text-muted">${command.timestamp}</small>
                                        </div>
                                        <div class="text-end">
                                            <strong class="fs-5">${command.total_price.toFixed(2)} €</strong>
                                            <div class="small text-muted">${command.files.length} fichier(s) <i class="bi bi-chevron-down"></i></div>
                                        </div>
                                    </div>
                                </a>
                                <div class="collapse" id="${collapseId}">
                                    <hr>
                                    <ul class="list-group list-group-flush">${filesHTML}</ul>
                                </div>
                            </div>
                        </div>
                    `;
                    container.innerHTML += cardHTML;
                });
            });
    };

    const showAdminPanel = () => {
        loginSection.classList.add('d-none');
        adminPanel.classList.remove('d-none');
        fetchAdminData();
        if (refreshInterval) clearInterval(refreshInterval);
        refreshInterval = setInterval(fetchAdminData, 5000);
    };

    loginForm.addEventListener('submit', function(event) {
        event.preventDefault();
        const formData = new FormData(loginForm);
        fetch('/login', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showAdminPanel();
                } else {
                    loginError.textContent = data.error;
                    loginError.classList.remove('d-none');
                }
            });
    });

    refreshBtn.addEventListener('click', fetchAdminData);

    const reprintToast = new bootstrap.Toast(document.getElementById('reprintToast'));
    document.getElementById('commands-container').addEventListener('click', function(event) {
        const reprintButton = event.target.closest('.reprint-btn');
        if (!reprintButton) return;

        // On empêche le collapse de se fermer si on clique sur le bouton
        event.stopPropagation();

        reprintButton.disabled = true;
        reprintButton.querySelector('.spinner-border').classList.remove('d-none');
        reprintButton.querySelector('.button-text').textContent = 'Envoi...';
        const data = {
            filename: reprintButton.dataset.filename,
            client_name: reprintButton.dataset.client,
            is_color: reprintButton.dataset.isColor === 'true',
            is_duplex: reprintButton.dataset.isDuplex === 'true'
        };
        fetch('/reprint', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(data)
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    reprintToast.show();
                } else {
                    alert(`Erreur de réimpression : ${result.error || 'Erreur inconnue'}`);
                }
            })
            .finally(() => {
                reprintButton.disabled = false;
                reprintButton.querySelector('.spinner-border').classList.add('d-none');
                reprintButton.querySelector('.button-text').textContent = 'Réimprimer';
            });
    });

    if (typeof isUserLoggedIn !== 'undefined' && isUserLoggedIn) {
        showAdminPanel();
    }
});
