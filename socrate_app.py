# socrate_app.py
import sys
import os
import queue
import logging
import logging.handlers
from datetime import datetime

# --- Importation des composants PyQt6 ---
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGroupBox, QLabel, QListWidget, QListWidgetItem, QPlainTextEdit,
    QFileDialog, QMessageBox, QDialog, QFormLayout, QLineEdit, QComboBox,
    QSpinBox, QCheckBox, QDialogButtonBox, QStyle, QGridLayout
)
from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import QIcon, QTextCursor, QFont

# --- Importation du moteur de l'application ---
from socrate_engine import (
    APP_NAME, LOG_DIR, IS_WINDOWS,
    OCRWatcher, load_config, save_config,
    LANG_MAP, SOURCE_ACTION_OPTIONS, OUTPUT_DEST_OPTIONS,
    FILE_RENAME_TOKENS, FOLDER_RENAME_TOKENS, COUNTER_RESET_OPTIONS,
    open_log_folder, add_to_startup, remove_from_startup, is_in_startup
)

# --- ✨ FEUILLE DE STYLE FINALE ✨ ---
STYLESHEET = """
/* --- Fenêtre principale et Dialogue --- */
QMainWindow, #MainAppWindow, QDialog {
    background-color: qradialgradient(
        cx: 0.3, cy: -0.4, fx: 0.3, fy: -0.4,
        radius: 1.35, stop: 0 #2d3a5a, stop: 1 #1d2538
    );
}
QWidget { font-family: 'Segoe UI', 'Calibri', 'Inter', sans-serif; color: #E0E0E0; font-size: 12pt; }
QGroupBox { font-size: 14pt; font-weight: bold; background-color: rgba(45, 58, 90, 0.5); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; margin-top: 10px; padding-top: 15px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; padding: 0 10px; color: #FFFFFF; }

/* --- Zones de texte et listes --- */
QPlainTextEdit, QListWidget { background-color: rgba(29, 37, 56, 0.8); border: none; border-radius: 8px; padding: 8px; }
QListWidget::item { padding: 10px; border-radius: 5px; }
QListWidget::item:selected, QListWidget::item:hover { background-color: rgba(0, 120, 215, 0.5); border: 1px solid #0078D7; }

/* --- Boutons --- */
QPushButton { background-color: #0078D7; color: white; border: none; padding: 8px 16px; border-radius: 8px; font-weight: bold; }
QPushButton:hover { background-color: #008ae6; }
QPushButton:disabled { background-color: #555; color: #999; }
#StartButton { background-color: #1a8a3a; }
#StartButton:hover { background-color: #2ab04c; }
#StopButton { background-color: #c92b2b; }
#StopButton:hover { background-color: #e04343; }

/* --- Boutons de dialogue --- */
#ValidateButton { background-color: #1a8a3a; }
#ValidateButton:hover { background-color: #2ab04c; }
#CancelButton { background-color: #c92b2b; }
#CancelButton:hover { background-color: #e04343; }

/* --- Icônes Flat Design --- */
#IconButton { background-color: rgba(255, 255, 255, 0.1); border-radius: 8px; min-width: 45px; max-width: 45px; min-height: 40px; max-height: 40px; font-size: 20pt; font-weight: normal; }
#IconButton:hover { background-color: #0078D7; }
#IconButton:disabled { background-color: transparent; color: #555; }

/* --- Bouton Quitter --- */
#QuitButton { background-color: #c92b2b; border-radius: 8px; min-width: 80px; }
#QuitButton:hover { background-color: #e04343; }
#AppTitle { font-size: 28pt; font-weight: bold; color: #FFFFFF; background: transparent; }

/* --- Éléments de formulaire --- */
QLineEdit, QComboBox, QSpinBox { background-color: #2d3a5a; border: 1px solid #555; border-radius: 5px; padding: 6px; min-height: 25px; }
QComboBox::drop-down { border: none; }
QComboBox QAbstractItemView {
    background-color: #2d3a5a;
    color: #E0E0E0;
    border: 1px solid #555;
    selection-background-color: #0078D7;
}
"""

class FolderSettingsDialog(QDialog):
    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.setWindowTitle("Paramètres de la Règle de Surveillance")
        # --- CORRECTION 1: Augmentation de la largeur minimale ---
        self.setMinimumSize(950, 750)
        self.config = config or {}
        self.result = None

        main_layout = QVBoxLayout(self)
        path_group = QGroupBox("📁 Dossier à surveiller")
        path_layout = QHBoxLayout()
        self.path_entry = QLineEdit(self.config.get("path", ""))
        self.path_button = QPushButton("...")
        self.path_button.setFixedWidth(40)
        self.path_button.clicked.connect(lambda: self.browse_for_entry(self.path_entry))
        path_layout.addWidget(self.path_entry)
        path_layout.addWidget(self.path_button)
        path_group.setLayout(path_layout)
        main_layout.addWidget(path_group)

        grid_layout = QGridLayout()
        
        source_group = QGroupBox("1. Fichier Original (Après OCR)")
        self.source_layout = QFormLayout(source_group)
        self.source_layout.setSpacing(10)

        self.source_action_menu = QComboBox()
        self.source_action_menu.addItems(SOURCE_ACTION_OPTIONS)
        self.source_action_menu.setCurrentText(self.config.get("source_action", SOURCE_ACTION_OPTIONS[0]))
        self.source_action_menu.currentTextChanged.connect(self.toggle_widgets)
        self.source_action_menu.setMinimumWidth(250)
        self.source_layout.addRow("Action :", self.source_action_menu)
        
        archive_path_widget, self.archive_path_entry = self._create_path_input(self.config.get("archive_path_pattern", ""))
        self.source_layout.addRow("Dossier d'archivage :", archive_path_widget)
        self.archive_path_row_index = self.source_layout.rowCount() - 1

        self.create_token_buttons(self.source_layout, self.archive_path_entry, FOLDER_RENAME_TOKENS)
        self.archive_tokens_row_index = self.source_layout.rowCount() - 1
        
        grid_layout.addWidget(source_group, 0, 0)
        
        output_group = QGroupBox("2. Fichier Traité (Avec OCR)")
        self.output_layout = QFormLayout(output_group)
        self.output_layout.setSpacing(10)

        self.lang_menu = QComboBox()
        self.lang_menu.addItems(LANG_MAP.keys())
        self.lang_menu.setCurrentText(self.config.get("lang", "Français"))
        self.lang_menu.setMinimumWidth(250)
        self.output_layout.addRow("Langue OCR :", self.lang_menu)

        self.output_dest_menu = QComboBox()
        self.output_dest_menu.addItems(OUTPUT_DEST_OPTIONS)
        self.output_dest_menu.setCurrentText(self.config.get("output_dest_type", OUTPUT_DEST_OPTIONS[0]))
        self.output_dest_menu.currentTextChanged.connect(self.toggle_widgets)
        self.output_dest_menu.setMinimumWidth(250)
        self.output_layout.addRow("Destination :", self.output_dest_menu)

        output_path_widget, self.output_path_entry = self._create_path_input(self.config.get("output_path_pattern", ""))
        self.output_layout.addRow("Dossier de destination :", output_path_widget)
        self.output_path_row_index = self.output_layout.rowCount() - 1

        self.create_token_buttons(self.output_layout, self.output_path_entry, FOLDER_RENAME_TOKENS)
        self.output_tokens_row_index = self.output_layout.rowCount() - 1

        grid_layout.addWidget(output_group, 0, 1)
        main_layout.addLayout(grid_layout)

        rename_group = QGroupBox("📝 Modèle de nommage du fichier")
        rename_layout = QFormLayout(rename_group)
        self.rename_pattern_entry = QLineEdit(self.config.get("rename_pattern", "[NOM_ORIGINAL]_ocr"))
        rename_layout.addRow(self.rename_pattern_entry)
        self.create_token_buttons(rename_layout, self.rename_pattern_entry, FILE_RENAME_TOKENS, "Jetons disponibles :")
        main_layout.addWidget(rename_group)
        
        counter_group = QGroupBox("🔢 Options du jeton [COMPTEUR]")
        counter_layout = QFormLayout(counter_group)
        self.counter_reset_menu = QComboBox()
        self.counter_reset_menu.addItems(COUNTER_RESET_OPTIONS)
        self.counter_reset_menu.setCurrentText(self.config.get("counter_reset", "Jamais"))
        self.counter_reset_menu.setMinimumWidth(200)
        self.counter_padding_spinbox = QSpinBox()
        self.counter_padding_spinbox.setRange(1, 10)
        self.counter_padding_spinbox.setValue(int(self.config.get("counter_padding", 3)))
        counter_layout.addRow("Réinitialiser le compteur :", self.counter_reset_menu)
        counter_layout.addRow("Nombre de chiffres (padding) :", self.counter_padding_spinbox)
        main_layout.addWidget(counter_group)

        button_box = QDialogButtonBox()
        validate_button = QPushButton("Valider")
        validate_button.setObjectName("ValidateButton")
        cancel_button = QPushButton("Annuler")
        cancel_button.setObjectName("CancelButton")
        button_box.addButton(validate_button, QDialogButtonBox.ButtonRole.AcceptRole)
        button_box.addButton(cancel_button, QDialogButtonBox.ButtonRole.RejectRole)
        button_box.accepted.connect(self.on_ok)
        button_box.rejected.connect(self.reject)
        main_layout.addWidget(button_box)

        self.toggle_widgets()

    def _create_path_input(self, initial_text=""):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit(initial_text)
        browse_button = QPushButton("...")
        browse_button.setFixedWidth(40)
        browse_button.clicked.connect(lambda: self.browse_for_entry(line_edit))
        layout.addWidget(line_edit)
        layout.addWidget(browse_button)
        return widget, line_edit

    def create_token_buttons(self, layout, entry_widget, tokens, label_text=None):
        token_widget = QWidget()
        token_layout = QHBoxLayout(token_widget)
        token_layout.setContentsMargins(0, 0, 0, 0)
        for token in tokens:
            btn = QPushButton(token)
            # --- CORRECTION 2: Ajout de border-radius ---
            btn.setStyleSheet("padding: 2px 5px; font-size: 9pt; font-weight: normal; border-radius: 4px;")
            btn.clicked.connect(lambda _, t=token, e=entry_widget: e.insert(t))
            token_layout.addWidget(btn)
        token_layout.addStretch()
        label_to_use = QLabel(label_text if label_text else "")
        layout.addRow(label_to_use, token_widget)

    def browse_for_entry(self, entry_widget):
        path = QFileDialog.getExistingDirectory(self, "Sélectionner un dossier", entry_widget.text())
        if path:
            entry_widget.setText(path)

    def toggle_widgets(self):
        is_move_action = self.source_action_menu.currentText() == "Déplacer l'original"
        self.source_layout.setRowVisible(self.archive_path_row_index, is_move_action)
        self.source_layout.setRowVisible(self.archive_tokens_row_index, is_move_action)
        is_specific_output = self.output_dest_menu.currentText() == "Dans un dossier spécifique"
        self.output_layout.setRowVisible(self.output_path_row_index, is_specific_output)
        self.output_layout.setRowVisible(self.output_tokens_row_index, is_specific_output)

    def on_ok(self):
        path = self.path_entry.text().strip()
        if not path or not os.path.isdir(path):
            QMessageBox.critical(self, "Erreur", "Le chemin du dossier à surveiller est invalide.")
            return
        self.result = {"path": os.path.normpath(path),"lang": self.lang_menu.currentText(),"source_action": self.source_action_menu.currentText(),"archive_path_pattern": self.archive_path_entry.text(),"output_dest_type": self.output_dest_menu.currentText(),"output_path_pattern": self.output_path_entry.text(),"rename_pattern": self.rename_pattern_entry.text(),"counter_reset": self.counter_reset_menu.currentText(),"counter_padding": self.counter_padding_spinbox.value()}
        self.accept()

class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setObjectName("MainAppWindow")
        self.setWindowTitle(f"{APP_NAME}")
        self.setMinimumSize(1100, 750)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.monitored_configs = []
        self.worker_thread = None
        self.log_queue = queue.Queue()
        self.setup_logging()
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        main_v_layout = QVBoxLayout(self.central_widget)
        self.setup_top_bar(main_v_layout)
        self.grid_layout = QGridLayout()
        main_v_layout.addLayout(self.grid_layout)
        self.setup_control_panel()
        self.setup_folders_panel()
        self.setup_log_panel()
        self.grid_layout.setColumnStretch(0, 1)
        self.grid_layout.setColumnStretch(1, 2)
        self.grid_layout.setRowStretch(0, 0)
        self.grid_layout.setRowStretch(1, 1)
        self.monitored_configs = load_config().get("monitored_configs", [])
        self.update_folder_listbox()
        self.on_folder_select()
    def setup_top_bar(self, parent_layout):
        top_bar_layout = QHBoxLayout()
        top_bar_layout.setContentsMargins(10, 5, 10, 15)
        title = QLabel(f"{APP_NAME}")
        title.setObjectName("AppTitle")
        quit_button = QPushButton("Quitter")
        quit_button.setObjectName("QuitButton")
        quit_button.clicked.connect(self.close)
        top_bar_layout.addWidget(title)
        top_bar_layout.addStretch()
        top_bar_layout.addWidget(quit_button)
        parent_layout.addLayout(top_bar_layout)
    def setup_control_panel(self):
        control_group = QGroupBox("🚀 Contrôles")
        layout = QVBoxLayout(control_group)
        button_layout = QHBoxLayout()
        self.start_button = QPushButton(" Démarrer")
        self.start_button.setObjectName("StartButton")
        self.start_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.start_button.setIconSize(QSize(22, 22))
        self.start_button.clicked.connect(self.start_surveillance)
        button_layout.addWidget(self.start_button)
        self.stop_button = QPushButton(" Arrêter")
        self.stop_button.setObjectName("StopButton")
        self.stop_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop))
        self.stop_button.setIconSize(QSize(22, 22))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_surveillance)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)
        if IS_WINDOWS:
            startup_layout = QHBoxLayout()
            startup_layout.addStretch()
            self.startup_check = QCheckBox("Lancer au démarrage")
            self.startup_check.setChecked(is_in_startup())
            self.startup_check.toggled.connect(self.update_startup_setting)
            startup_layout.addWidget(self.startup_check)
            startup_layout.addStretch()
            layout.addLayout(startup_layout)
        self.grid_layout.addWidget(control_group, 0, 0)
    def setup_folders_panel(self):
        folders_group = QGroupBox("Règles de Surveillance")
        layout = QVBoxLayout(folders_group)
        self.folder_listbox = QListWidget()
        self.folder_listbox.itemSelectionChanged.connect(self.on_folder_select)
        layout.addWidget(self.folder_listbox, 1)
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        add_btn = QPushButton("+")
        add_btn.setObjectName("IconButton")
        add_btn.setToolTip("Ajouter une nouvelle règle")
        add_btn.clicked.connect(self.add_folder)
        self.edit_btn = QPushButton()
        self.edit_btn.setObjectName("IconButton")
        self.edit_btn.setIcon(QIcon("icon_settings.png")) 
        self.edit_btn.setIconSize(QSize(24, 24))
        self.edit_btn.setToolTip("Modifier la règle sélectionnée")
        self.edit_btn.clicked.connect(self.edit_folder)
        self.remove_btn = QPushButton("×")
        self.remove_btn.setObjectName("IconButton")
        self.remove_btn.setToolTip("Supprimer la règle sélectionnée")
        self.remove_btn.clicked.connect(self.remove_folder)
        buttons_layout.addWidget(add_btn)
        buttons_layout.addWidget(self.edit_btn)
        buttons_layout.addWidget(self.remove_btn)
        layout.addLayout(buttons_layout)
        self.grid_layout.addWidget(folders_group, 1, 0)
    def setup_log_panel(self):
        log_group = QGroupBox("Journal d'événements")
        layout = QVBoxLayout(log_group)
        self.log_textbox = QPlainTextEdit()
        self.log_textbox.setReadOnly(True)
        self.log_textbox.setStyleSheet("font-family: 'Fira Code', 'Consolas', 'Courier New', monospace; font-size: 10pt;")
        layout.addWidget(self.log_textbox, 1)
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        open_log_folder_btn = QPushButton("Logs")
        open_log_folder_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        open_log_folder_btn.setToolTip("Ouvrir le dossier contenant les fichiers de log")
        open_log_folder_btn.clicked.connect(open_log_folder)
        clear_log_btn = QPushButton("Nettoyer")
        clear_log_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogDiscardButton))
        clear_log_btn.setToolTip("Effacer le journal d'événements affiché")
        clear_log_btn.clicked.connect(self.log_textbox.clear)
        buttons_layout.addWidget(open_log_folder_btn)
        buttons_layout.addWidget(clear_log_btn)
        layout.addLayout(buttons_layout)
        self.grid_layout.addWidget(log_group, 0, 1, 2, 1)
        
    def setup_logging(self):
        class QueueHandler(logging.Handler):
            def __init__(self, log_queue):
                super().__init__()
                self.log_queue = log_queue
            def emit(self, record):
                self.log_queue.put(self.format(record))
        
        logger = logging.getLogger()
        if not logger.handlers:
            logger.setLevel(logging.INFO)
            
            # --- MODIFICATION : Remplacement de FileHandler par TimedRotatingFileHandler ---
            #
            # Crée un fichier de log par jour (à minuit) et conserve les 7 derniers jours.
            file_handler = logging.handlers.TimedRotatingFileHandler(
                os.path.join(LOG_DIR, "app.log"),
                when='midnight', # Rotation chaque jour à minuit
                interval=1,
                backupCount=7 # Garde 7 jours d'historique (ex: app.log.2025-07-31)
            )
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
            logger.addHandler(file_handler)
            
            # Le handler pour l'interface graphique (via la queue) reste le même
            queue_handler = QueueHandler(self.log_queue)
            queue_handler.setFormatter(logging.Formatter('%(message)s'))
            logger.addHandler(queue_handler)

        self.log_timer = QTimer(self)
        self.log_timer.timeout.connect(self.process_log_queue)
        self.log_timer.start(250)
        
    def process_log_queue(self):
        while not self.log_queue.empty():
            record = self.log_queue.get()
            
            # Si on dépasse 500 lignes, on supprime la plus ancienne
            if self.log_textbox.blockCount() > 500:
                cursor = self.log_textbox.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.Start)
                cursor.select(QTextCursor.SelectionType.LineUnderCursor)
                cursor.removeSelectedText()
                cursor.deletePreviousChar() # Nettoie le saut de ligne résiduel
            
            now = datetime.now().strftime('%H:%M:%S')
            color = "#A9B7C6"
            if "[ERROR]" in record or "[CRITICAL]" in record: color = "#FF7575"
            elif "[WARNING]" in record: color = "#FFD666"
            elif "terminé" in record or "sauvé" in record or "Lancement" in record or "démarrée": color = "#78FFA4"
            line = f'<span style="color: #888;">[{now}]</span> <span style="color: {color};">{record}</span>'
            self.log_textbox.appendHtml(line)
        self.log_textbox.moveCursor(QTextCursor.MoveOperation.End)
    def log(self, msg, level="info"): logging.info(msg) if level=="info" else logging.error(msg)
    def on_save_config(self):
        save_config({"monitored_configs": self.monitored_configs})
        self.log("Configuration sauvegardée.")
    def update_folder_listbox(self):
        self.folder_listbox.clear()
        for i, config in enumerate(self.monitored_configs):
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            item = QListWidgetItem(icon, f"  {config['path']}")
            item.setData(Qt.ItemDataRole.UserRole, i)
            self.folder_listbox.addItem(item)
    def on_folder_select(self):
        is_selected = bool(self.folder_listbox.selectedItems())
        self.edit_btn.setEnabled(is_selected)
        self.remove_btn.setEnabled(is_selected)
    def add_folder(self):
        dialog = FolderSettingsDialog(self)
        if dialog.exec():
            result = dialog.result
            if any(c['path'] == result['path'] for c in self.monitored_configs):
                QMessageBox.warning(self, "Doublon", "Ce dossier est déjà surveillé.")
                return
            self.monitored_configs.append(result)
            self.update_folder_listbox()
            self.log(f"Nouvelle règle ajoutée pour : {result['path']}")
    def edit_folder(self):
        selected_items = self.folder_listbox.selectedItems()
        if not selected_items: return
        idx = selected_items[0].data(Qt.ItemDataRole.UserRole)
        dialog = FolderSettingsDialog(self, config=self.monitored_configs[idx])
        if dialog.exec():
            result = dialog.result
            for i, conf in enumerate(self.monitored_configs):
                if i != idx and conf['path'] == result['path']:
                    QMessageBox.warning(self, "Doublon", "Ce dossier est déjà surveillé par une autre règle.")
                    return
            self.monitored_configs[idx] = result
            self.update_folder_listbox()
            self.log(f"Règle modifiée pour : {result['path']}")
            self.folder_listbox.setCurrentItem(self.folder_listbox.item(idx))
    def remove_folder(self):
        selected_items = self.folder_listbox.selectedItems()
        if not selected_items: return
        idx = selected_items[0].data(Qt.ItemDataRole.UserRole)
        path = self.monitored_configs[idx]['path']
        reply = QMessageBox.question(self, "Confirmation", 
                                     f"Voulez-vous vraiment supprimer la règle pour :\n\n{path} ?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            del self.monitored_configs[idx]
            self.update_folder_listbox()
            self.log(f"Règle supprimée pour : {path}")
    def start_surveillance(self):
        if not self.monitored_configs:
            QMessageBox.warning(self, "Aucune règle", "Veuillez ajouter au moins un dossier à surveiller.")
            return
        configs_map = {config['path']: config for config in self.monitored_configs}
        self.worker_thread = OCRWatcher(configs_map, self.log_queue)
        self.worker_thread.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.log("Surveillance démarrée.")
    def stop_surveillance(self):
        if self.worker_thread: self.worker_thread.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
    def update_startup_setting(self):
        if not IS_WINDOWS: return
        try:
            # --- CORRECTION ICI : on n'envoie plus d'argument ---
            if self.startup_check.isChecked():
                add_to_startup()
            else:
                remove_from_startup()
        except Exception as e:
            self.log(f"Erreur lors de la modification du démarrage : {e}", "error")
    def closeEvent(self, event):
        self.log("Fermeture de l'application...")
        self.on_save_config()
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_surveillance()
            self.worker_thread.join(timeout=2)
        self.log_timer.stop()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = App()
    window.show()
    sys.exit(app.exec())