# --- PARTIE 1/2 : MOTEUR & LOGIQUE DE FOND ---

import os
import sys
import json
import logging
import threading
import time
import shutil
import subprocess
from datetime import datetime
import socket
import webview
import appdirs
import pytesseract
import fitz  # PyMuPDF
from pypdf import PdfWriter
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- Configuration et Constantes ---
APP_NAME = "sOCRate"
APP_AUTHOR = "Amaury Poussier"
IS_WINDOWS = sys.platform == "win32"

APP_DATA_DIR = appdirs.user_data_dir(APP_NAME, APP_AUTHOR)
LOG_DIR = appdirs.user_log_dir(APP_NAME, APP_AUTHOR)
os.makedirs(APP_DATA_DIR, exist_ok=True); os.makedirs(LOG_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
STATE_FILE = os.path.join(APP_DATA_DIR, "state.json")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

LANG_MAP = {"Français": "fra", "English": "eng", "Português": "por"}
SOURCE_ACTION_OPTIONS = ["Conserver l'original", "Déplacer l'original", "Écraser l'original"]
OUTPUT_DEST_OPTIONS = ["Dans un sous-dossier 'Traités_OCR'", "Dans le même dossier que l'original", "Dans un dossier spécifique"]
FILE_RENAME_TOKENS = ["[NOM_ORIGINAL]", "[DATE]", "[HEURE]", "[COMPTEUR]", "[POIDS_FICHIER]", "[NOMBRE_PAGES]"]
FOLDER_RENAME_TOKENS = ["[NOM_UTILISATEUR]", "[NOM_ORDINATEUR]", "[DATE]"]
COUNTER_RESET_OPTIONS = ["Jamais", "Chaque jour", "Chaque mois", "Chaque année"]

# --- Logique Tesseract ---
if getattr(sys, 'frozen', False):
    tesseract_folder = os.path.join(sys._MEIPASS, 'Tesseract-OCR')
    pytesseract.pytesseract.tesseract_cmd = os.path.join(tesseract_folder, 'tesseract.exe')
    os.environ['TESSDATA_PREFIX'] = os.path.join(tesseract_folder, 'tessdata')
else:
    # Pour Windows en dev, décommentez si Tesseract n'est pas dans le PATH
    # pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    pass

# --- Fonctions utilitaires ---
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f: return json.load(f)
        except (json.JSONDecodeError, AttributeError): return {}
    return {}

def save_state(state_data):
    with open(STATE_FILE, 'w') as f: json.dump(state_data, f, indent=4)

def get_next_counter(rule_path, reset_interval, padding):
    state = load_state(); counters = state.get("counters", {})
    rule_state = counters.get(rule_path, {"value": 0, "last_used": "1970-01-01"})
    current_val = rule_state["value"]; last_used_date = datetime.strptime(rule_state["last_used"], "%Y-%m-%d").date()
    today = datetime.now().date(); reset = False
    if reset_interval == "Chaque jour" and today != last_used_date: reset = True
    elif reset_interval == "Chaque mois" and (today.year != last_used_date.year or today.month != last_used_date.month): reset = True
    elif reset_interval == "Chaque année" and today.year != last_used_date.year: reset = True
    current_val = 1 if reset else current_val + 1
    counters[rule_path] = {"value": current_val, "last_used": today.strftime("%Y-%m-%d")}
    state["counters"] = counters; save_state(state)
    return str(current_val).zfill(padding)

def format_filesize(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "Ko", "Mo", "Go", "To"); i = 0; p = 1024
    while size_bytes >= p and i < len(size_name) - 1: size_bytes /= p; i += 1
    return f"{size_bytes:.1f}{size_name[i]}"

def build_dynamic_path(pattern):
    now = datetime.now()
    try: user_name = os.getlogin()
    except OSError: user_name = "inconnu"
    computer_name = socket.gethostname()
    replacements = {"[NOM_UTILISATEUR]": user_name, "[NOM_ORDINATEUR]": computer_name, "[DATE]": now.strftime("%Y-%m-%d")}
    path = pattern
    for token, value in replacements.items(): path = path.replace(token, value)
    return os.path.normpath(path)

def build_new_filename(config, original_path, rule_path):
    pattern = config.get("rename_pattern", "[NOM_ORIGINAL]_ocr")
    original_filename = os.path.basename(original_path)
    try: file_size = format_filesize(os.path.getsize(original_path))
    except FileNotFoundError: file_size = "0B"
    try:
        with fitz.open(original_path) as doc: page_count = len(doc)
    except Exception: page_count = 0
    name, ext = os.path.splitext(original_filename)
    now = datetime.now()
    reset_interval = config.get("counter_reset", "Jamais")
    try: padding = int(config.get("counter_padding", 3))
    except (ValueError, TypeError): padding = 3
    replacements = {
        "[NOM_ORIGINAL]": name, "[DATE]": now.strftime("%Y-%m-%d"), "[HEURE]": now.strftime("%H-%M-%S"),
        "[COMPTEUR]": get_next_counter(rule_path, reset_interval, padding),
        "[POIDS_FICHIER]": file_size, "[NOMBRE_PAGES]": str(page_count)
    }
    new_name = pattern
    for token, value in replacements.items(): new_name = new_name.replace(token, value)
    return "".join(c for c in new_name if c.isalnum() or c in " ._-") + ext

class OCRWatcher(threading.Thread):
    def __init__(self, configs_map, api_bridge):
        super().__init__()
        self.configs_map = configs_map
        self.api = api_bridge
        self.observer = Observer()
        self.stop_event = threading.Event()

    def run(self):
        self.log("Lancement du scan des fichiers existants...")
        for path in self.configs_map.keys():
            try:
                for entry in os.scandir(path):
                    # On vérifie si c'est un fichier PDF
                    if entry.is_file() and entry.name.lower().endswith('.pdf'):
                        self.log(f"Fichier existant trouvé : {entry.name}")
                        # On lance le traitement dans un thread pour ne pas bloquer le scan
                        # des autres dossiers si un fichier est très long à traiter.
                        threading.Thread(target=self.process_pdf, args=(entry.path,)).start()
            except FileNotFoundError:
                self.log(f"Le dossier {path} n'a pas été trouvé lors du scan initial.", "error")
        self.log("Scan initial terminé. Passage en mode surveillance.")
        
        event_handler = self.PDFHandler(self)
        for path in self.configs_map.keys():
            self.observer.schedule(event_handler, path, recursive=False)
            self.log(f"Surveillance démarrée pour : {path}")
        self.observer.start(); self.stop_event.wait()
        self.observer.stop(); self.observer.join()
        self.log("Surveillance arrêtée.")

    def stop(self): self.stop_event.set()
    def log(self, message, level="info"): self.api.log(message, level)

    def pdf_has_text(self, pdf_path):
        try:
            with fitz.open(pdf_path) as doc: return any(len(page.get_text().strip()) > 50 for page in doc)
        except Exception as e:
            self.log(f"Impossible de vérifier le texte de {os.path.basename(pdf_path)}: {e}", "warning"); return False

    def process_pdf(self, pdf_path):
        base_folder = os.path.dirname(pdf_path); filename = os.path.basename(pdf_path)
        config = self.configs_map.get(base_folder)
        if not config: return
        self.log(f"Traitement de '{filename}'...")
        if self.pdf_has_text(pdf_path): self.log(f"'{filename}' contient déjà du texte. Ignoré.", "info"); return

        try:
            new_filename = build_new_filename(config, pdf_path, config['path'])
            output_dest_type = config.get("output_dest_type", "Dans un sous-dossier 'Traités_OCR'")
            if output_dest_type == "Dans un dossier spécifique": output_folder = build_dynamic_path(config.get("output_path_pattern"))
            elif output_dest_type == "Dans le même dossier que l'original": output_folder = base_folder
            else: output_folder = os.path.join(base_folder, "Traités_OCR")
            os.makedirs(output_folder, exist_ok=True); output_path = os.path.join(output_folder, new_filename)

            with fitz.open(pdf_path) as pdf_document, PdfWriter() as merger:
                for i, page in enumerate(pdf_document):
                    self.log(f"   -> OCR Page {i+1}/{len(pdf_document)} de '{filename}'...")
                    pix = page.get_pixmap(dpi=300); img_bytes = pix.tobytes("ppm")
                    pdf_page_with_ocr_bytes = pytesseract.image_to_pdf_or_hocr(img_bytes, lang=LANG_MAP[config['lang']], extension='pdf')
                    with fitz.open("pdf", pdf_page_with_ocr_bytes) as temp_pdf: merger.append(fileobj=temp_pdf.write(), import_outline=False)
                temp_output_path = output_path + ".tmp"
                with open(temp_output_path, "wb") as f_out: merger.write(f_out)

            source_action = config.get("source_action", "Conserver l'original")
            if source_action == "Écraser l'original":
                final_path = os.path.join(base_folder, new_filename)
                shutil.move(temp_output_path, final_path)
                if pdf_path != final_path: os.remove(pdf_path)
                self.log(f"'{filename}' écrasé par la version OCRisée '{new_filename}'.")
            elif source_action == "Déplacer l'original":
                archive_folder = build_dynamic_path(config.get("archive_path_pattern"))
                os.makedirs(archive_folder, exist_ok=True); archive_path = os.path.join(archive_folder, filename)
                shutil.move(pdf_path, archive_path); shutil.move(temp_output_path, output_path)
                self.log(f"'{filename}' traité. Original déplacé vers '{archive_folder}', OCR sauvé dans '{output_folder}'.")
            elif source_action == "Conserver l'original":
                shutil.move(temp_output_path, output_path)
                self.log(f"'{filename}' traité. Original conservé, OCR sauvé dans '{output_folder}'.")
        except Exception as e: self.log(f"Erreur critique sur '{filename}': {e}", "error")

    class PDFHandler(FileSystemEventHandler):
        def __init__(self, watcher): self.watcher = watcher; self.last_processed = {}
        def on_created(self, event):
            if event.is_directory or not event.src_path.lower().endswith('.pdf'): return
            if event.src_path in self.last_processed and time.time() - self.last_processed[event.src_path] < 5: return
            self.last_processed[event.src_path] = time.time(); time.sleep(2)
            self.watcher.log(f"Nouveau fichier détecté : {event.src_path}")
            threading.Thread(target=self.watcher.process_pdf, args=(event.src_path,)).start()

# --- FIN DE LA PARTIE 1/2 ---

# --- PARTIE 2/2 : PONT API & LANCEUR D'APPLICATION ---

class Api:
    """
    Cette classe est exposée à JavaScript. Toutes ses méthodes publiques 
    sont appelables depuis le frontend via `window.pywebview.api`.
    """
    def __init__(self):
        self.monitored_configs = self.load_config()
        self.worker_thread = None
        self.window = None

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try: return json.load(open(CONFIG_FILE, 'r')).get("monitored_configs", [])
            except (json.JSONDecodeError, AttributeError): return []
        return []

    def save_config(self):
        with open(CONFIG_FILE, 'w') as f: json.dump({"monitored_configs": self.monitored_configs}, f, indent=4)
        self.log("Configuration sauvegardée.")

    def log(self, message, level="info"):
        if self.window:
            escaped_message = json.dumps(message)
            self.window.evaluate_js(f'window.app.addLog({escaped_message}, "{level.upper()}");')
        logger = logging.getLogger()
        if level.lower() == 'error': logger.error(message)
        else: logger.info(message)

    def get_initial_data(self):
        return {
            "rules": self.monitored_configs, "is_windows": IS_WINDOWS,
            "is_in_startup": self.is_in_startup() if IS_WINDOWS else False,
            "constants": {
                "SOURCE_ACTION_OPTIONS": SOURCE_ACTION_OPTIONS, "OUTPUT_DEST_OPTIONS": OUTPUT_DEST_OPTIONS,
                "FILE_RENAME_TOKENS": FILE_RENAME_TOKENS, "FOLDER_RENAME_TOKENS": FOLDER_RENAME_TOKENS,
                "COUNTER_RESET_OPTIONS": COUNTER_RESET_OPTIONS, "LANG_MAP": LANG_MAP
            }
        }

    def save_rule(self, config_data, is_new, original_path=None):
        if is_new:
            if any(c['path'] == config_data['path'] for c in self.monitored_configs):
                return {"success": False, "message": "Ce dossier est déjà surveillé."}
            self.monitored_configs.append(config_data)
            self.log(f"Nouvelle règle ajoutée pour : {config_data['path']}")
        else:
            idx = next((i for i, conf in enumerate(self.monitored_configs) if conf['path'] == original_path), -1)
            if idx != -1: self.monitored_configs[idx] = config_data; self.log(f"Règle modifiée pour : {config_data['path']}")
            else: return {"success": False, "message": "Règle originale non trouvée."}
        self.save_config()
        return {"success": True, "rules": self.monitored_configs}

    def remove_rule(self, path_to_remove):
        self.monitored_configs = [conf for conf in self.monitored_configs if conf['path'] != path_to_remove]
        self.save_config(); self.log(f"Règle de surveillance supprimée pour : {path_to_remove}")
        return {"success": True, "rules": self.monitored_configs}

    def start_monitoring(self):
        if not self.monitored_configs: return {"success": False, "message": "Veuillez ajouter au moins une règle."}
        if self.worker_thread and self.worker_thread.is_alive(): return {"success": False, "message": "La surveillance est déjà en cours."}
        configs_map = {config['path']: config for config in self.monitored_configs}
        self.worker_thread = OCRWatcher(configs_map, self); self.worker_thread.start()
        return {"success": True}
        
    def stop_monitoring(self):
        if self.worker_thread and self.worker_thread.is_alive():
            self.log("Demande d'arrêt de la surveillance...")
            self.worker_thread.stop()
            return {"success": True}
        return {"success": False, "message": "Aucune surveillance en cours."}

    def browse_folder(self):
        result = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return result[0] if result else None
    
    def open_log_folder(self):
        self.log(f"Ouverture du dossier des logs : {LOG_DIR}")
        if IS_WINDOWS: os.startfile(LOG_DIR)
        else: subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", LOG_DIR])
    
    def request_quit(self):
        if self.window: self.window.destroy()

    def shutdown(self):
        self.log("Séquence de fermeture initiée...")
        self.save_config()
        if self.worker_thread and self.worker_thread.is_alive():
            self.log("Arrêt du thread de surveillance...")
            self.worker_thread.stop()
            self.worker_thread.join(timeout=2)
            if self.worker_thread.is_alive(): self.log("Le thread de surveillance n'a pas pu s'arrêter à temps.", "ERROR")
            else: self.log("Thread de surveillance arrêté proprement.")
        self.log("Application fermée.")

    def update_startup_setting(self, should_enable):
        if not IS_WINDOWS: return
        if should_enable: self.add_to_startup()
        else: self.remove_from_startup()

    def get_exe_path(self):
        if getattr(sys, 'frozen', False): return sys.executable
        return os.path.abspath(sys.argv[0])

    def add_to_startup(self):
        try:
            import winreg
            key = winreg.HKEY_CURRENT_USER; subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE) as reg_key:
                winreg.SetValueEx(reg_key, APP_NAME, 0, winreg.REG_SZ, self.get_exe_path())
            self.log("Ajouté au démarrage de Windows.")
        except Exception as e: self.log(f"Erreur d'ajout au démarrage : {e}", "error")

    def remove_from_startup(self):
        try:
            import winreg
            key = winreg.HKEY_CURRENT_USER; subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, subkey, 0, winreg.KEY_WRITE) as reg_key:
                winreg.DeleteValue(reg_key, APP_NAME)
            self.log("Retiré du démarrage de Windows.")
        except FileNotFoundError: pass
        except Exception as e: self.log(f"Erreur de suppression du démarrage : {e}", "error")

    def is_in_startup(self):
        if not IS_WINDOWS: return False
        try:
            import winreg
            key = winreg.HKEY_CURRENT_USER; subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, subkey, 0, winreg.KEY_READ) as reg_key:
                winreg.QueryValueEx(reg_key, APP_NAME)
            return True
        except FileNotFoundError: return False

    def confirm_dialog(self, title, message):
        """Expose une boîte de dialogue de confirmation au frontend."""
        return self.window.create_confirmation_dialog(title, message)

# --- Point d'Entrée de l'Application ---
if __name__ == '__main__':
    api = Api()
    
    window = webview.create_window(
        f"{APP_NAME} - OCR Automatisé",
        'gui/index.html',
        js_api=api,
        width=1100, height=750, min_size=(900, 600)
    )
    api.window = window
    
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s',
                        handlers=[logging.FileHandler(LOG_FILE, 'a', 'utf-8')])
    
    window.events.closing += api.shutdown

    webview.start(debug=True) # Mettre debug=False pour la version finale

# --- FIN DE LA PARTIE 2/2 ---