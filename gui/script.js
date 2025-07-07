// gui/script.js - VERSION COMPLÈTE ET CORRIGÉE

window.addEventListener('pywebviewready', () => {
    window.app = {
        rules: [], selectedRulePath: null, isMonitoring: false,
        constants: {}, settingsModal: null,

        async init() {
            this.cacheDOMElements();
            this.bindEvents();
            this.settingsModal = new bootstrap.Modal(this.dom.settingsModalEl);

            try {
                const initialData = await window.pywebview.api.get_initial_data();
                this.rules = initialData.rules;
                this.constants = initialData.constants;
                this.renderRulesList();
                if (initialData.is_windows) this.renderWindowsStartup(initialData.is_in_startup);
                this.addLog("Application prête.", "INFO");
            } catch (e) { console.error("Erreur d'initialisation:", e); this.addLog("Erreur critique au chargement.", "ERROR"); }
        },

        cacheDOMElements() {
            this.dom = {
                rulesList: document.getElementById('rules-list'),
                addRuleBtn: document.getElementById('add-rule-btn'),
                editRuleBtn: document.getElementById('edit-rule-btn'),
                removeRuleBtn: document.getElementById('remove-rule-btn'),
                startBtn: document.getElementById('start-btn'),
                stopBtn: document.getElementById('stop-btn'),
                logsFolderBtn: document.getElementById('logs-folder-btn'),
                quitBtn: document.getElementById('quit-btn'),
                logEntries: document.getElementById('log-entries'),
                settingsModalEl: document.getElementById('settings-modal'),
                settingsModalTitle: document.getElementById('settings-modal-title'),
                settingsModalBody: document.getElementById('settings-modal-body'),
                saveSettingsBtn: document.getElementById('save-settings-btn'),
                windowsStartupContainer: document.getElementById('windows-startup-container'),
            };
        },

        bindEvents() {
            this.dom.addRuleBtn.addEventListener('click', () => this.showSettingsView(true));
            this.dom.editRuleBtn.addEventListener('click', () => this.showSettingsView(false));
            this.dom.removeRuleBtn.addEventListener('click', () => this.removeRule());
            this.dom.startBtn.addEventListener('click', () => this.startMonitoring());
            this.dom.stopBtn.addEventListener('click', () => this.stopMonitoring());
            this.dom.logsFolderBtn.addEventListener('click', () => window.pywebview.api.open_log_folder());
            this.dom.quitBtn.addEventListener('click', () => window.pywebview.api.request_quit());
        },

        renderRulesList() {
            this.dom.rulesList.innerHTML = '';
            if (this.rules.length === 0) this.dom.rulesList.innerHTML = `<div class="list-group-item text-muted">Aucune règle définie.</div>`;
            this.rules.forEach(rule => {
                const item = document.createElement('a');
                item.href = '#';
                item.className = 'list-group-item list-group-item-action';
                item.textContent = rule.path;
                item.dataset.path = rule.path;
                if (rule.path === this.selectedRulePath) item.classList.add('active');
                item.addEventListener('click', e => { e.preventDefault(); this.selectRule(rule.path); });
                this.dom.rulesList.appendChild(item);
            });
            this.updateButtonStates();
        },
        
        selectRule(path) { this.selectedRulePath = this.selectedRulePath === path ? null : path; this.renderRulesList(); },
        updateButtonStates() {
            const hasSelection = !!this.selectedRulePath;
            this.dom.editRuleBtn.disabled = !hasSelection || this.isMonitoring;
            this.dom.removeRuleBtn.disabled = !hasSelection || this.isMonitoring;
            this.dom.addRuleBtn.disabled = this.isMonitoring;
            this.dom.startBtn.disabled = this.isMonitoring || this.rules.length === 0;
            this.dom.stopBtn.disabled = !this.isMonitoring;
        },

        showSettingsView(isNew) {
            const rule = isNew ? {} : this.rules.find(r => r.path === this.selectedRulePath);
            if (!isNew && !rule) return;
            this.dom.settingsModalTitle.textContent = isNew ? 'Ajouter une nouvelle règle' : 'Modifier la règle';
            this.dom.settingsModalBody.innerHTML = this.buildSettingsForm(rule);
            this.dom.saveSettingsBtn.onclick = () => this.saveRule(isNew, rule ? rule.path : null);
            this.settingsModal.show();
            document.getElementById('source_action').addEventListener('change', () => this.toggleDynamicFields());
            document.getElementById('output_dest_type').addEventListener('change', () => this.toggleDynamicFields());
            this.toggleDynamicFields();
            document.querySelectorAll('.browse-btn').forEach(btn => btn.addEventListener('click', async (e) => {
                const targetInputId = e.target.dataset.target;
                const folderPath = await window.pywebview.api.browse_folder();
                if (folderPath) document.getElementById(targetInputId).value = folderPath;
            }));
            document.querySelectorAll('.token-btn').forEach(btn => btn.addEventListener('click', (e) => {
                const targetInputId = e.target.dataset.target; const token = e.target.textContent;
                const input = document.getElementById(targetInputId); input.value += token; input.focus();
            }));
        },

        buildSettingsForm(rule = {}) {
            const createOptions = (options, selected) => options.map(opt => `<option value="${opt}" ${opt === selected ? 'selected' : ''}>${opt}</option>`).join('');
            const createTokenButtons = (tokens, targetId) => tokens.map(t => `<button type="button" class="btn btn-outline-secondary btn-sm me-1 mb-1 token-btn" data-target="${targetId}">${t}</button>`).join('');
            return `
                <form id="settings-form" onsubmit="return false;">
                    <div class="mb-3"><label for="path" class="form-label fw-bold">Dossier à surveiller</label><div class="input-group"><input type="text" class="form-control" id="path" value="${rule.path || ''}" required><button class="btn btn-outline-secondary browse-btn" type="button" data-target="path">...</button></div></div>
                    <div class="card mb-3"><div class="card-header">1. Gestion du Fichier Original</div><div class="card-body"><label for="source_action" class="form-label">Après traitement OCR :</label><select class="form-select" id="source_action">${createOptions(this.constants.SOURCE_ACTION_OPTIONS, rule.source_action || "Conserver l'original")}</select><div id="archive-path-container" class="mt-3"><label for="archive_path_pattern" class="form-label">Modèle du dossier d'archivage :</label><div class="input-group"><input type="text" class="form-control" id="archive_path_pattern" value="${rule.archive_path_pattern || ''}" placeholder="C:/Archives/[DATE]"><button class="btn btn-outline-secondary browse-btn" type="button" data-target="archive_path_pattern">...</button></div><div class="mt-2">${createTokenButtons(this.constants.FOLDER_RENAME_TOKENS, 'archive_path_pattern')}</div></div></div></div>
                    <div class="card"><div class="card-header">2. Gestion du Fichier Traité (avec OCR)</div><div class="card-body"><div class="mb-3"><label for="lang" class="form-label">Langue OCR :</label><select class="form-select" id="lang">${createOptions(Object.keys(this.constants.LANG_MAP), rule.lang || "Français")}</select></div><div class="mb-3"><label for="output_dest_type" class="form-label">Sauvegarder le nouveau fichier :</label><select class="form-select" id="output_dest_type">${createOptions(this.constants.OUTPUT_DEST_OPTIONS, rule.output_dest_type || "Dans un sous-dossier 'Traités_OCR'")}</select></div><div id="output-path-container" class="mb-3"><label for="output_path_pattern" class="form-label">Modèle du dossier de destination :</label><div class="input-group"><input type="text" class="form-control" id="output_path_pattern" value="${rule.output_path_pattern || ''}" placeholder="D:/Factures_Traitées/[DATE]"><button class="btn btn-outline-secondary browse-btn" type="button" data-target="output_path_pattern">...</button></div><div class="mt-2">${createTokenButtons(this.constants.FOLDER_RENAME_TOKENS, 'output_path_pattern')}</div></div><div class="mb-3"><label for="rename_pattern" class="form-label">Modèle de nommage du fichier :</label><input type="text" class="form-control" id="rename_pattern" value="${rule.rename_pattern || '[NOM_ORIGINAL]_ocr'}" placeholder="[NOM_ORIGINAL]_[DATE]"><div class="mt-2">${createTokenButtons(this.constants.FILE_RENAME_TOKENS, 'rename_pattern')}</div></div></div></div>
                    <div class="card mt-3"><div class="card-header">Options du jeton [COMPTEUR]</div><div class="card-body"><div class="row"><div class="col-md-6 mb-3 mb-md-0"><label for="counter_reset" class="form-label">Réinitialiser :</label><select class="form-select" id="counter_reset">${createOptions(this.constants.COUNTER_RESET_OPTIONS, rule.counter_reset || "Jamais")}</select></div><div class="col-md-6"><label for="counter_padding" class="form-label">Nombre de chiffres :</label><input type="number" class="form-control" id="counter_padding" min="1" max="10" value="${rule.counter_padding || '3'}"></div></div></div></div>
                </form>
            `;
        },
        
        toggleDynamicFields() {
            document.getElementById('archive-path-container').style.display = (document.getElementById('source_action').value === "Déplacer l'original") ? 'block' : 'none';
            document.getElementById('output-path-container').style.display = (document.getElementById('output_dest_type').value === "Dans un dossier spécifique") ? 'block' : 'none';
        },

        async saveRule(isNew, originalPath) {
            const configData = {
                path: document.getElementById('path').value,
                source_action: document.getElementById('source_action').value, archive_path_pattern: document.getElementById('archive_path_pattern').value,
                lang: document.getElementById('lang').value, output_dest_type: document.getElementById('output_dest_type').value,
                output_path_pattern: document.getElementById('output_path_pattern').value, rename_pattern: document.getElementById('rename_pattern').value,
                counter_reset: document.getElementById('counter_reset').value, counter_padding: document.getElementById('counter_padding').value
            };
            const result = await window.pywebview.api.save_rule(configData, isNew, originalPath);
            if (result.success) { this.rules = result.rules; this.renderRulesList(); this.settingsModal.hide(); }
            else { alert(`Erreur : ${result.message}`); }
        },
        
        async removeRule() {
            if (!this.selectedRulePath) return;
            const confirmation = await window.pywebview.api.confirm_dialog('Confirmation', `Supprimer la règle pour :\n${this.selectedRulePath} ?`);
            if (confirmation) {
                const result = await window.pywebview.api.remove_rule(this.selectedRulePath);
                if (result.success) { this.selectedRulePath = null; this.rules = result.rules; this.renderRulesList(); }
            }
        },

        async startMonitoring() {
            const result = await window.pywebview.api.start_monitoring();
            if(result.success) { this.isMonitoring = true; this.updateButtonStates(); } else { alert(`Erreur : ${result.message}`); }
        },

        async stopMonitoring() {
            const result = await window.pywebview.api.stop_monitoring();
            if(result.success) { this.isMonitoring = false; this.updateButtonStates(); }
        },

        addLog(message, level = 'INFO') {
            const p = document.createElement('div'); const time = new Date().toLocaleTimeString('fr-FR');
            p.innerHTML = `<small class="text-muted me-2">[${time}]</small> <span class="fw-bold text-${level === 'ERROR' ? 'danger' : 'primary'}">${level}:</span> ${message}`;
            this.dom.logEntries.prepend(p);
        },
        
        renderWindowsStartup(isInStartup) {
            this.dom.windowsStartupContainer.innerHTML = `
                <div class="form-check form-switch d-flex justify-content-center align-items-center h-100">
                  <input class="form-check-input" type="checkbox" role="switch" id="startup-checkbox" ${isInStartup ? 'checked' : ''}>
                  <label class="form-check-label ms-2" for="startup-checkbox">Lancer au démarrage</label>
                </div>`;
            document.getElementById('startup-checkbox').addEventListener('change', e => window.pywebview.api.update_startup_setting(e.target.checked));
        }
    };
    window.app.init();
});