# socrate_engine.py

import os
import sys
import json
import logging
import threading
import time
import queue
import shutil
import subprocess
from datetime import datetime
import socket

# --- Dépendances ---
import appdirs
from PIL import Image
import io

# --- Bibliothèques pour l'OCR et la surveillance ---
import pytesseract
import fitz  # PyMuPDF
from pytesseract import Output
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- Constantes et Fonctions Utilitaires ---
APP_NAME = "sOCRate"
APP_AUTHOR = "Amaury Poussier"
IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    import winreg
APP_DATA_DIR = appdirs.user_data_dir(APP_NAME, APP_AUTHOR)
LOG_DIR = appdirs.user_log_dir(APP_NAME, APP_AUTHOR)
os.makedirs(APP_DATA_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
STATE_FILE = os.path.join(APP_DATA_DIR, "state.json")
LOG_FILE = os.path.join(LOG_DIR, "app.log") # Le fichier de log principal
LANG_MAP = {"Français": "fra", "English": "eng", "Português": "por"}
SOURCE_ACTION_OPTIONS = ["Conserver l'original", "Déplacer l'original", "Écraser l'original"]
OUTPUT_DEST_OPTIONS = ["Dans un sous-dossier 'Traités_OCR'", "Dans le même dossier que l'original", "Dans un dossier spécifique"]
FILE_RENAME_TOKENS = ["[NOM_ORIGINAL]", "[DATE]", "[HEURE]", "[COMPTEUR]", "[POIDS_FICHIER]", "[NOMBRE_PAGES]"]
FOLDER_RENAME_TOKENS = ["[NOM_UTILISATEUR]", "[NOM_ORDINATEUR]", "[DATE]"]
COUNTER_RESET_OPTIONS = ["Jamais", "Chaque jour", "Chaque mois", "Chaque année"]

def setup_tesseract_data():
    try:
        cache_dir = appdirs.user_data_dir(APP_NAME, APP_AUTHOR)
        tessdata_cache_path = os.path.join(cache_dir, 'tessdata_v1')
        if os.path.exists(tessdata_cache_path): return tessdata_cache_path
        bundle_dir = getattr(sys, '_MEIPASS', os.path.abspath(os.path.join(os.path.dirname(sys.executable), '..', 'Resources')))
        source_tessdata_path = os.path.join(bundle_dir, 'Tesseract-OCR', 'share', 'tessdata')
        if not os.path.exists(source_tessdata_path):
            logging.error(f"Source tessdata introuvable à {source_tessdata_path}")
            return None
        logging.info(f"Copie de tessdata vers le cache : {tessdata_cache_path}")
        shutil.copytree(source_tessdata_path, tessdata_cache_path)
        return tessdata_cache_path
    except Exception as e:
        logging.error(f"Erreur fatale lors de la configuration du cache de Tesseract : {e}")
        return None

# --- ✨ NOUVEAU BLOC : Logique Tesseract robuste pour la compilation ✨ ---
TESSDATA_DIR_CONFIG = ''
# Détecte si l'application est "gelée" (compilée par PyInstaller)
is_frozen = getattr(sys, 'frozen', False)

if is_frozen:
    # --- Mode Compilé ---
    # Le dossier de base de l'application une fois compilée
    bundle_dir = sys._MEIPASS
    
    # Chemin explicite vers l'exécutable Tesseract inclus dans notre application
    tesseract_executable_path = os.path.join(bundle_dir, 'Tesseract-OCR', 'tesseract.exe' if IS_WINDOWS else 'bin/tesseract')
    pytesseract.pytesseract.tesseract_cmd = tesseract_executable_path
    
    # Chemin vers le dossier des données linguistiques (tessdata)
    if IS_WINDOWS:
        tessdata_path = os.path.join(bundle_dir, 'Tesseract-OCR', 'tessdata')
    else: # Pour macOS, la structure est différente
        tessdata_path = os.path.join(bundle_dir, 'Tesseract-OCR', 'share', 'tessdata')
    
    if os.path.exists(tessdata_path):
        os.environ['TESSDATA_PREFIX'] = tessdata_path
        TESSDATA_DIR_CONFIG = f'--tessdata-dir "{tessdata_path}"'
    else:
        logging.error(f"Dossier tessdata introuvable dans le bundle à {tessdata_path}")

else:
    # --- Mode Développement (logique inchangée) ---
    if IS_WINDOWS:
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    else: # macOS / Linux
        for path in ['/opt/homebrew/bin/tesseract', '/usr/local/bin/tesseract', '/usr/bin/tesseract']:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                break

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, AttributeError): return {"monitored_configs": []}
    return {"monitored_configs": []}

def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except (json.JSONDecodeError, AttributeError): return {}
    return {}

def save_state(state_data):
    with open(STATE_FILE, 'w', encoding='utf-8') as f: json.dump(state_data, f, indent=4)

def get_next_counter(rule_path, reset_interval, padding):
    state = load_state(); counters = state.get("counters", {}); rule_state = counters.get(rule_path, {"value": 0, "last_used": "1970-01-01"})
    current_val = rule_state["value"]; last_used_date = datetime.strptime(rule_state["last_used"], "%Y-%m-%d").date()
    today = datetime.now().date(); reset = False
    if reset_interval == "Chaque jour" and today != last_used_date: reset = True
    elif reset_interval == "Chaque mois" and (today.year != last_used_date.year or today.month != last_used_date.month): reset = True
    elif reset_interval == "Chaque année" and today.year != last_used_date.year: reset = True
    current_val = 1 if reset else current_val + 1; counters[rule_path] = {"value": current_val, "last_used": today.strftime("%Y-%m-%d")}
    state["counters"] = counters; save_state(state); return str(current_val).zfill(padding)

def format_filesize(size_bytes):
    if size_bytes == 0: return "0B"
    size_name = ("B", "Ko", "Mo", "Go", "To"); i, p = 0, 1024
    while size_bytes >= p and i < len(size_name) - 1: size_bytes /= p; i += 1
    return f"{size_bytes:.1f}{size_name[i]}"

def build_dynamic_path(pattern):
    now = datetime.now(); user_name = os.getlogin() if hasattr(os, 'getlogin') else "inconnu"; computer_name = socket.gethostname()
    replacements = {"[NOM_UTILISATEUR]": user_name, "[NOM_ORDINATEUR]": computer_name, "[DATE]": now.strftime("%Y-%m-%d")}
    path = pattern
    for token, value in replacements.items(): path = path.replace(token, value)
    return os.path.normpath(path)

def build_new_filename(config, original_path, rule_path):
    pattern = config.get("rename_pattern", "[NOM_ORIGINAL]_ocr"); original_filename = os.path.basename(original_path)
    try: file_size = format_filesize(os.path.getsize(original_path))
    except FileNotFoundError: file_size = "0B"
    try:
        with fitz.open(original_path) as doc: page_count = len(doc)
    except Exception: page_count = 0
    name, ext = os.path.splitext(original_filename); now = datetime.now(); reset_interval = config.get("counter_reset", "Jamais")
    try: padding = int(config.get("counter_padding", 3))
    except (ValueError, TypeError): padding = 3
    replacements = {"[NOM_ORIGINAL]": name, "[DATE]": now.strftime("%Y-%m-%d"), "[HEURE]": now.strftime("%H-%M-%S"), "[COMPTEUR]": get_next_counter(rule_path, reset_interval, padding), "[POIDS_FICHIER]": file_size, "[NOMBRE_PAGES]": str(page_count)}
    new_name = pattern
    for token, value in replacements.items(): new_name = new_name.replace(token, value)
    return "".join(c for c in new_name if c.isalnum() or c in " ._-") + ext

def open_log_folder():
    logging.info(f"Ouverture du dossier des logs : {LOG_DIR}");
    if IS_WINDOWS: os.startfile(LOG_DIR)
    else: subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", LOG_DIR])

def get_exe_path():
    if getattr(sys, 'frozen', False): return sys.executable
    return os.path.abspath(__file__)

def add_to_startup():
    if not IS_WINDOWS: return
    try:
        key = winreg.HKEY_CURRENT_USER; subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE) as reg_key: winreg.SetValueEx(reg_key, APP_NAME, 0, winreg.REG_SZ, f'"{get_exe_path()}"')
        logging.info("Ajouté au démarrage de Windows.")
    except Exception as e: logging.error(f"Erreur d'ajout au démarrage : {e}")

def remove_from_startup():
    if not IS_WINDOWS: return
    try:
        key = winreg.HKEY_CURRENT_USER; subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(key, subkey, 0, winreg.KEY_WRITE) as reg_key: winreg.DeleteValue(reg_key, APP_NAME)
        logging.info("Retiré du démarrage de Windows.")
    except FileNotFoundError: pass
    except Exception as e: logging.error(f"Erreur de suppression du démarrage : {e}")

def is_in_startup():
    if not IS_WINDOWS: return False
    try:
        key = winreg.HKEY_CURRENT_USER; subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.OpenKey(key, subkey, 0, winreg.KEY_READ) as reg_key: winreg.QueryValueEx(reg_key, APP_NAME)
        return True
    except FileNotFoundError: return False

class OCRWatcher(threading.Thread):
    def __init__(self, configs_map, log_queue):
        super().__init__()
        self.configs_map = configs_map
        self.log_queue = log_queue
        self.observer = Observer()
        self.stop_event = threading.Event()

    def run(self):
        self.log("Lancement du scan des fichiers existants...")
        for path in self.configs_map.keys():
            try:
                for entry in os.scandir(path):
                    if entry.is_file() and entry.name.lower().endswith('.pdf'):
                        self.log(f"Fichier existant trouvé : {entry.name}")
                        threading.Thread(target=self.process_pdf, args=(entry.path,)).start()
            except FileNotFoundError:
                self.log(f"Le dossier {path} n'a pas été trouvé lors du scan initial.", "error")
        self.log("Scan initial terminé. Passage en mode surveillance.")
        event_handler = self.PDFHandler(self)
        for path in self.configs_map.keys():
            self.observer.schedule(event_handler, path, recursive=False)
        self.observer.start()
        self.stop_event.wait()
        self.observer.stop()
        self.observer.join()
        self.log("Surveillance arrêtée.")

    def stop(self):
        self.stop_event.set()

    def log(self, message, level="info"):
        self.log_queue.put(f"[{level.upper()}] {message}")

    def pdf_has_text(self, pdf_path):
        try:
            with fitz.open(pdf_path) as doc:
                return any(len(page.get_text().strip()) > 50 for page in doc)
        except Exception as e:
            self.log(f"Impossible de vérifier le texte de {os.path.basename(pdf_path)}: {e}", "warning")
            return False

    def wait_for_file_stability(self, file_path, max_wait_time=30, check_interval=1):
        start_time = time.time()
        while time.time() - start_time < max_wait_time:
            try:
                initial_size = os.path.getsize(file_path)
                time.sleep(check_interval)
                current_size = os.path.getsize(file_path)
                if initial_size == current_size:
                    self.log(f"Le fichier '{os.path.basename(file_path)}' est stable.", "info")
                    return True
            except FileNotFoundError:
                self.log(f"Le fichier '{os.path.basename(file_path)}' a disparu.", "warning")
                return False
        self.log(f"Le fichier '{os.path.basename(file_path)}' n'est pas devenu stable. Ignoré.", "error")
        return False

    def process_pdf(self, pdf_path):
        base_folder = os.path.dirname(pdf_path); filename = os.path.basename(pdf_path)
        config = self.configs_map.get(base_folder)
        if not config: return
        self.log(f"Traitement de '{filename}'...")
        if self.pdf_has_text(pdf_path):
            self.log(f"'{filename}' contient déjà du texte. Ignoré.", "info"); return
        temp_output_path = ""
        try:
            new_filename = build_new_filename(config, pdf_path, config['path'])
            output_dest_type = config.get("output_dest_type", "Dans un sous-dossier 'Traités_OCR'")
            if output_dest_type == "Dans un dossier spécifique": output_folder = build_dynamic_path(config.get("output_path_pattern"))
            elif output_dest_type == "Dans le même dossier que l'original": output_folder = base_folder
            else: output_folder = os.path.join(base_folder, "Traités_OCR")
            os.makedirs(output_folder, exist_ok=True)
            output_path = os.path.join(output_folder, new_filename)
            temp_output_path = output_path + ".tmp"
            pdf_document = fitz.open(pdf_path)
            for i, page in enumerate(pdf_document):
                self.log(f"   -> OCR Page {i+1}/{len(pdf_document)} de '{filename}'...")
                pix = page.get_pixmap(dpi=300); img_bytes = pix.tobytes("png")
                ocr_data = pytesseract.image_to_data(Image.open(io.BytesIO(img_bytes)), lang=LANG_MAP[config['lang']], output_type=Output.DICT, config=TESSDATA_DIR_CONFIG)
                for j in range(len(ocr_data['text'])):
                    text = ocr_data['text'][j]; conf = int(ocr_data['conf'][j])
                    if conf > 60 and text.strip():
                        x, y, w, h = ocr_data['left'][j], ocr_data['top'][j], ocr_data['width'][j], ocr_data['height'][j]
                        rect = fitz.Rect(x, y, x + w, y + h) / 300 * 72
                        page.insert_text((rect.x0, rect.y1), text, fontsize=h / 300 * 72 * 0.8, render_mode=3)
            pdf_document.save(temp_output_path, garbage=4, deflate=True, clean=True); pdf_document.close()
            original_size = os.path.getsize(pdf_path); new_size = os.path.getsize(temp_output_path)
            size_change = (new_size / original_size - 1) * 100 if original_size > 0 else 0
            self.log(f"   -> OCR terminé. Augmentation de la taille de {size_change:+.1f}%.", "info")
            source_action = config.get("source_action", "Conserver l'original")
            if source_action == "Écraser l'original":
                final_path = os.path.join(base_folder, new_filename)
                shutil.move(temp_output_path, final_path)
                if pdf_path != final_path: os.remove(pdf_path)
                self.log(f"'{filename}' écrasé par la version OCR '{new_filename}'.")
            elif source_action == "Déplacer l'original":
                archive_folder = build_dynamic_path(config.get("archive_path_pattern")); os.makedirs(archive_folder, exist_ok=True)
                archive_path = os.path.join(archive_folder, filename)
                shutil.move(pdf_path, archive_path); shutil.move(temp_output_path, output_path)
                self.log(f"'{filename}' traité. Original déplacé, OCR sauvé.")
            elif source_action == "Conserver l'original":
                shutil.move(temp_output_path, output_path)
                self.log(f"'{filename}' traité. Original conservé, OCR sauvé.")
        except Exception as e:
            self.log(f"Erreur critique sur '{filename}': {e}", "error")
        finally:
            if os.path.exists(temp_output_path): os.remove(temp_output_path)

    class PDFHandler(FileSystemEventHandler):
        def __init__(self, watcher):
            self.watcher = watcher
            self.last_processed = {}

        def on_created(self, event):
            if event.is_directory or not event.src_path.lower().endswith('.pdf'): return
            if event.src_path in self.last_processed and time.time() - self.last_processed[event.src_path] < 5: return
            self.last_processed[event.src_path] = time.time()
            self.watcher.log(f"Nouveau fichier détecté : {event.src_path}. Vérification...")
            threading.Thread(target=self.check_and_process, args=(event.src_path,)).start()

        def check_and_process(self, path):
            if self.watcher.wait_for_file_stability(path):
                threading.Thread(target=self.watcher.process_pdf, args=(path,)).start()