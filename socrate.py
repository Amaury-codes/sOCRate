# --- PARTIE 1/2 : MOTEUR & LOGIQUE DE FOND ---

import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
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

# --- Dépendances à installer: pip install customtkinter pillow watchdog pytesseract PyMuPDF pypdf appdirs ---
import appdirs
from PIL import Image
import io

# --- Bibliothèques pour l'OCR ---
import pytesseract
import fitz  # PyMuPDF
from pypdf import PdfWriter
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

def setup_tesseract_data():
    """Vérifie si les données Tesseract sont dans un cache local, sinon les copie depuis le paquet de l'application."""
    try:
        cache_dir = appdirs.user_data_dir(APP_NAME, APP_AUTHOR)
        # CORRECTION : On utilise le chiffre '1' et non la lettre 'l'.
        tessdata_cache_path = os.path.join(cache_dir, 'tessdata_v1') 

        if os.path.exists(tessdata_cache_path):
            return tessdata_cache_path

        if hasattr(sys, '_MEIPASS'):
            bundle_dir = sys._MEIPASS
        else:
            bundle_dir = os.path.abspath(os.path.join(os.path.dirname(sys.executable), '..', 'Resources'))
        
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

# --- Configuration et Constantes ---
APP_NAME = "sOCRate"
APP_AUTHOR = "Amaury Poussier"
IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import winreg

APP_DATA_DIR = appdirs.user_data_dir(APP_NAME, APP_AUTHOR)
LOG_DIR = appdirs.user_log_dir(APP_NAME, APP_AUTHOR)
os.makedirs(APP_DATA_DIR, exist_ok=True); os.makedirs(LOG_DIR, exist_ok=True)

CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
STATE_FILE = os.path.join(APP_DATA_DIR, "state.json")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

LANG_MAP = {"Français": "fra", "English": "eng", "Português": "por"}
SOURCE_ACTION_OPTIONS = ["Conserver l'original", "Déplacer l'original", "Écraser l'original"]
OUTPUT_DEST_OPTIONS = ["Dans un sous-ddessier 'Traités_OCR'", "Dans le même dossier que l'original", "Dans un dossier spécifique"]
FILE_RENAME_TOKENS = ["[NOM_ORIGINAL]", "[DATE]", "[HEURE]", "[COMPTEUR]", "[POIDS_FICHIER]", "[NOMBRE_PAGES]"]
FOLDER_RENAME_TOKENS = ["[NOM_UTILISATEUR]", "[NOM_ORDINATEUR]", "[DATE]"]
COUNTER_RESET_OPTIONS = ["Jamais", "Chaque jour", "Chaque mois", "Chaque année"]

# --- Logique Tesseract (Approche Finale via Cache Applicatif - CORRIGÉE) ---
TESSDATA_DIR_CONFIG = ''
IS_WINDOWS = sys.platform == "win32"

if getattr(sys, 'frozen', False):
    # --- Mode compilé ---
    if hasattr(sys, '_MEIPASS'):
        bundle_dir = sys._MEIPASS
    else:
        bundle_dir = os.path.abspath(os.path.join(os.path.dirname(sys.executable), '..', 'Resources'))
    
    tesseract_executable_path = os.path.join(bundle_dir, 'Tesseract-OCR', 'bin', 'tesseract')
    pytesseract.pytesseract.tesseract_cmd = tesseract_executable_path

    cached_tessdata_path = setup_tesseract_data()

    if cached_tessdata_path:
        os.environ['TESSDATA_PREFIX'] = cached_tessdata_path
        # La variable de configuration doit pointer vers le dossier qui contient les fichiers .traineddata
        TESSDATA_DIR_CONFIG = f'--tessdata-dir "{cached_tessdata_path}"'
    else:
        logging.error("Le chemin des données Tesseract n'a pas pu être configuré. L'OCR va échouer.")

else:
    # --- Mode développement ---
    if IS_WINDOWS:
        pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    else: # macOS / Linux
        tesseract_path_dev = '/opt/homebrew/bin/tesseract'
        if not os.path.exists(tesseract_path_dev):
            tesseract_path_dev = '/usr/local/bin/tesseract'
        if os.path.exists(tesseract_path_dev):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path_dev

# --- Fonctions utilitaires (inchangées) ---
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
    try: user_name = os.getlogin()
    except OSError: user_name = "inconnu"
    computer_name = socket.gethostname()
    reset_interval = config.get("counter_reset", "Jamais")
    try: padding = int(config.get("counter_padding", 3))
    except (ValueError, TypeError): padding = 3
    replacements = {
        "[NOM_ORIGINAL]": name, "[DATE]": now.strftime("%Y-%m-%d"), "[HEURE]": now.strftime("%H-%M-%S"),
        "[COMPTEUR]": get_next_counter(rule_path, reset_interval, padding),
        "[POIDS_FICHIER]": file_size, "[NOMBRE_PAGES]": str(page_count),
        "[NOM_UTILISATEUR]": user_name, "[NOM_ORDINATEUR]": computer_name
    }
    new_name = pattern
    for token, value in replacements.items(): new_name = new_name.replace(token, value)
    return "".join(c for c in new_name if c.isalnum() or c in " ._-") + ext

class OCRWatcher(threading.Thread):
    def __init__(self, configs_map, log_queue):
        super().__init__(); self.configs_map = configs_map; self.log_queue = log_queue
        self.observer = Observer(); self.stop_event = threading.Event()

    def run(self):
        self.log("Lancement du scan des fichiers existants...")
        for path in self.configs_map.keys():
            try:
                for entry in os.scandir(path):
                    if entry.is_file() and entry.name.lower().endswith('.pdf'):
                        self.log(f"Fichier existant trouvé : {entry.name}")
                        threading.Thread(target=self.process_pdf, args=(entry.path,)).start()
            except FileNotFoundError: self.log(f"Le dossier {path} n'a pas été trouvé lors du scan initial.", "error")
        self.log("Scan initial terminé. Passage en mode surveillance.")
        event_handler = self.PDFHandler(self)
        for path in self.configs_map.keys(): self.observer.schedule(event_handler, path, recursive=False)
        self.observer.start(); self.stop_event.wait()
        self.observer.stop(); self.observer.join()
        self.log("Surveillance arrêtée.")

    def stop(self): self.stop_event.set()
    def log(self, message, level="info"): self.log_queue.put(f"[{level.upper()}] {message}")

    def pdf_has_text(self, pdf_path):
        try:
            with fitz.open(pdf_path) as doc: return any(len(page.get_text().strip()) > 50 for page in doc)
        except Exception as e: self.log(f"Impossible de vérifier le texte de {os.path.basename(pdf_path)}: {e}", "warning"); return False

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
                self.log(f"Le fichier '{os.path.basename(file_path)}' a disparu pendant la vérification.", "warning")
                return False
        self.log(f"Le fichier '{os.path.basename(file_path)}' n'est pas devenu stable après {max_wait_time}s. Ignoré.", "error")
        return False

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
                    pix = page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    img_buffer = io.BytesIO()
                    img.save(img_buffer, format='JPEG', quality=85)
                    img_buffer.seek(0)
                    compressed_img_object = Image.open(img_buffer)
                    # --- MODIFICATION FINALE ICI ---
                    pdf_page_with_ocr_bytes = pytesseract.image_to_pdf_or_hocr(compressed_img_object, lang=LANG_MAP[config['lang']], extension='pdf', config=TESSDATA_DIR_CONFIG)
                    pdf_stream = io.BytesIO(pdf_page_with_ocr_bytes)
                    merger.append(pdf_stream)
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
            self.last_processed[event.src_path] = time.time()
            self.watcher.log(f"Nouveau fichier détecté : {event.src_path}. Vérification de la stabilité...")
            threading.Thread(target=self.check_and_process, args=(event.src_path,)).start()

        def check_and_process(self, path):
            if self.watcher.wait_for_file_stability(path):
                threading.Thread(target=self.watcher.process_pdf, args=(path,)).start()

# --- FIN DE LA PARTIE 1/2 ---

# --- PARTIE 2/2 : INTERFACE GRAPHIQUE & LANCEUR ---

class FolderSettingsDialog(ctk.CTkToplevel):
    def __init__(self, parent, config=None):
        super().__init__(parent); self.transient(parent)
        self.title("Paramètres de la Règle de Surveillance"); self.geometry("900x620")
        self.result = None; self.create_widgets(config); self.grab_set()

    def create_widgets(self, config):
        config = config or {}
        self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(self, text="Dossier à surveiller :", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 5), sticky="w")
        path_frame = ctk.CTkFrame(self, fg_color="transparent"); path_frame.grid(row=1, column=0, padx=20, sticky="ew")
        self.path_entry = ctk.CTkEntry(path_frame); self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.path_entry.insert(0, config.get("path", "")); ctk.CTkButton(path_frame, text="...", width=30, command=lambda: self.browse_for_entry(self.path_entry)).pack(side="left")

        main_grid = ctk.CTkFrame(self, fg_color="transparent"); main_grid.grid(row=2, column=0, padx=20, pady=15, sticky="nsew")
        main_grid.grid_columnconfigure((0, 1), weight=1)

        source_frame = ctk.CTkFrame(main_grid); source_frame.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        ctk.CTkLabel(source_frame, text="1. Fichier Original", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        ctk.CTkLabel(source_frame, text="Après traitement OCR :").pack(padx=10, anchor="w")
        self.source_action_menu = ctk.CTkOptionMenu(source_frame, values=SOURCE_ACTION_OPTIONS, command=self.toggle_widgets)
        self.source_action_menu.pack(padx=10, fill="x", pady=5); self.source_action_menu.set(config.get("source_action", "Conserver l'original"))
        self.archive_frame = ctk.CTkFrame(source_frame, fg_color="transparent")
        ctk.CTkLabel(self.archive_frame, text="Modèle du dossier d'archivage :").pack(anchor="w")
        archive_entry_frame = ctk.CTkFrame(self.archive_frame, fg_color="transparent"); archive_entry_frame.pack(fill="x")
        self.archive_path_entry = ctk.CTkEntry(archive_entry_frame, placeholder_text="Ex: C:/Archives/[DATE]")
        self.archive_path_entry.pack(side="left", fill="x", expand=True, padx=(0,10)); self.archive_path_entry.insert(0, config.get("archive_path_pattern", ""))
        ctk.CTkButton(archive_entry_frame, text="Parcourir...", command=lambda: self.browse_for_entry(self.archive_path_entry)).pack(side="left")
        self.create_token_buttons(self.archive_frame, self.archive_path_entry, FOLDER_RENAME_TOKENS)

        output_frame = ctk.CTkFrame(main_grid); output_frame.grid(row=0, column=1, sticky="nsew", padx=(10,0))
        ctk.CTkLabel(output_frame, text="2. Fichier Traité (avec OCR)", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=5)
        ctk.CTkLabel(output_frame, text="Langue OCR :").pack(padx=10, anchor="w")
        self.lang_menu = ctk.CTkOptionMenu(output_frame, values=list(LANG_MAP.keys())); self.lang_menu.pack(padx=10, fill="x", pady=5)
        self.lang_menu.set(config.get("lang", "Français"))
        ctk.CTkLabel(output_frame, text="Sauvegarder le nouveau fichier :").pack(padx=10, anchor="w", pady=(10,0))
        self.output_dest_menu = ctk.CTkOptionMenu(output_frame, values=OUTPUT_DEST_OPTIONS, command=self.toggle_widgets)
        self.output_dest_menu.pack(padx=10, fill="x", pady=5); self.output_dest_menu.set(config.get("output_dest_type", "Dans un sous-dossier 'Traités_OCR'"))
        self.output_path_frame = ctk.CTkFrame(output_frame, fg_color="transparent")
        ctk.CTkLabel(self.output_path_frame, text="Modèle du dossier de destination :").pack(anchor="w")
        output_entry_frame = ctk.CTkFrame(self.output_path_frame, fg_color="transparent"); output_entry_frame.pack(fill="x")
        self.output_path_entry = ctk.CTkEntry(output_entry_frame, placeholder_text="Ex: D:/Factures/[DATE]")
        self.output_path_entry.pack(side="left", fill="x", expand=True, padx=(0,10)); self.output_path_entry.insert(0, config.get("output_path_pattern", ""))
        ctk.CTkButton(output_entry_frame, text="Parcourir...", command=lambda: self.browse_for_entry(self.output_path_entry)).pack(side="left")
        self.create_token_buttons(self.output_path_frame, self.output_path_entry, FOLDER_RENAME_TOKENS)

        bottom_frame = ctk.CTkFrame(self, fg_color="transparent"); bottom_frame.grid(row=3, column=0, padx=20, sticky="nsew")
        bottom_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bottom_frame, text="Modèle de nommage du fichier :", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(10,0))
        self.rename_pattern_entry = ctk.CTkEntry(bottom_frame, placeholder_text="Ex: [NOM_ORIGINAL]_[DATE]")
        self.rename_pattern_entry.pack(fill="x", pady=5); self.rename_pattern_entry.insert(0, config.get("rename_pattern", "[NOM_ORIGINAL]_ocr"))
        self.create_token_buttons(bottom_frame, self.rename_pattern_entry, FILE_RENAME_TOKENS, rows=2)
        counter_frame = ctk.CTkFrame(bottom_frame); counter_frame.pack(pady=10, fill="x")
        counter_frame.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(counter_frame, text="Options du jeton [COMPTEUR] :", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, columnspan=2, sticky="w", padx=10)
        ctk.CTkLabel(counter_frame, text="Réinitialiser :").grid(row=1, column=0, sticky="w", pady=(5,0), padx=10)
        self.counter_reset_menu = ctk.CTkOptionMenu(counter_frame, values=COUNTER_RESET_OPTIONS)
        self.counter_reset_menu.grid(row=2, column=0, sticky="ew", padx=10); self.counter_reset_menu.set(config.get("counter_reset", "Jamais"))
        ctk.CTkLabel(counter_frame, text="Nombre de chiffres :").grid(row=1, column=1, sticky="w", pady=(5,0), padx=10)
        self.counter_padding_entry = ctk.CTkEntry(counter_frame, placeholder_text="ex: 3")
        self.counter_padding_entry.grid(row=2, column=1, sticky="ew", padx=10); self.counter_padding_entry.insert(0, str(config.get("counter_padding", 3)))
        
        btn_frame = ctk.CTkFrame(self, fg_color="transparent"); btn_frame.grid(row=4, column=0, pady=20)
        ctk.CTkButton(btn_frame, text="✔ Valider", command=self.on_ok, fg_color="#2E7D32", hover_color="#1B5E20").pack(side="left", padx=10)
        ctk.CTkButton(btn_frame, text="Annuler", command=self.on_cancel, fg_color="#D32F2F", hover_color="#B71C1C").pack(side="left", padx=10)
        self.toggle_widgets()

    def create_token_buttons(self, parent, entry, tokens, rows=1, padx=0):
        token_frame = ctk.CTkFrame(parent, fg_color="transparent"); token_frame.pack(fill="x", padx=padx, pady=(0,5))
        ctk.CTkLabel(token_frame, text="Ajouter jeton:").pack(side="left", padx=(0, 5))
        items_per_row = (len(tokens) + rows - 1) // rows
        for i in range(rows):
            row_frame = ctk.CTkFrame(token_frame, fg_color="transparent"); row_frame.pack(fill="x")
            for j in range(items_per_row):
                token_idx = i * items_per_row + j
                if token_idx < len(tokens):
                    token = tokens[token_idx]
                    btn = ctk.CTkButton(row_frame, text=token, text_color=("gray10", "gray90"), fg_color="transparent", border_width=1, width=20, command=lambda t=token, e=entry: e.insert(tk.END, t))
                    btn.pack(side="left", padx=2, pady=2)

    def toggle_widgets(self, _=None):
        if self.source_action_menu.get() == "Déplacer l'original": self.archive_frame.pack(fill="x", padx=10, pady=5)
        else: self.archive_frame.pack_forget()
        if self.output_dest_menu.get() == "Dans un dossier spécifique": self.output_path_frame.pack(fill="x", padx=10, pady=5)
        else: self.output_path_frame.pack_forget()

    def browse_for_entry(self, entry_widget):
        path = filedialog.askdirectory(parent=self)
        if path: entry_widget.delete(0, tk.END); entry_widget.insert(0, path)

    def on_ok(self):
        if not os.path.isdir(self.path_entry.get()): messagebox.showerror("Erreur", "Le chemin à surveiller n'est pas valide.", parent=self); return
        try:
            padding = int(self.counter_padding_entry.get()); assert 1 <= padding <= 10
        except (ValueError, AssertionError): messagebox.showerror("Erreur", "Le 'Nombre de chiffres' doit être un nombre de 1 à 10.", parent=self); return
        self.result = {
            "path": self.path_entry.get(), "lang": self.lang_menu.get(), "source_action": self.source_action_menu.get(),
            "archive_path_pattern": self.archive_path_entry.get(), "output_dest_type": self.output_dest_menu.get(),
            "output_path_pattern": self.output_path_entry.get(), "rename_pattern": self.rename_pattern_entry.get(),
            "counter_reset": self.counter_reset_menu.get(), "counter_padding": self.counter_padding_entry.get()
        }
        self.destroy()

    def on_cancel(self): self.result = None; self.destroy()

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        try:
            if sys.platform == "win32": self.state('zoomed')
            elif sys.platform == "darwin": self.attributes('-zoomed', True)
            else: self.attributes('-zoomed', 1)
        except tk.TclError:
            print("Mode maximisé standard non supporté, passage en mode manuel.")
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
        self.title(f"{APP_NAME} - OCR Automatisé"); self.minsize(800, 600)
        ctk.set_appearance_mode("light"); self.grid_columnconfigure(0, weight=1); self.grid_rowconfigure(0, weight=1)
        self.main_frame = ctk.CTkFrame(self); self.main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1); self.main_frame.grid_rowconfigure(1, weight=1); self.main_frame.grid_rowconfigure(3, weight=2)
        self.monitored_configs = []; self.worker_thread = None
        self.setup_control_panel(); self.setup_folders_panel(); self.setup_log_panel()
        self.monitored_configs = self.load_config(); self.update_folder_listbox()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_control_panel(self):
        control_frame = ctk.CTkFrame(self.main_frame); control_frame.grid(row=0, column=0, columnspan=2, padx=10, pady=10, sticky="ew")
        ctk.CTkLabel(control_frame, text=APP_NAME, font=ctk.CTkFont(size=20, weight="bold")).pack(side="left", padx=20)
        self.quit_button = ctk.CTkButton(control_frame, text="Quitter", command=self.on_closing, fg_color="gray"); self.quit_button.pack(side="right", padx=10)
        self.start_button = ctk.CTkButton(control_frame, text="▶ Démarrer", command=self.start_surveillance, fg_color="#2E7D32", hover_color="#1B5E20"); self.start_button.pack(side="right", padx=10)
        self.stop_button = ctk.CTkButton(control_frame, text="⏹️ Arrêter", state="disabled", fg_color="#D32F2F", hover_color="#B71C1C", command=self.stop_surveillance); self.stop_button.pack(side="right", padx=10)
        if IS_WINDOWS:
            self.startup_check = ctk.CTkCheckBox(control_frame, text="Lancer au démarrage", command=self.update_startup_setting)
            self.startup_check.pack(side="right", padx=20)
            if self.is_in_startup(): self.startup_check.select()

    def setup_folders_panel(self):
        folders_frame = ctk.CTkFrame(self.main_frame); folders_frame.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        folders_frame.grid_columnconfigure(0, weight=1); folders_frame.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(folders_frame, text="Règles de Surveillance", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(5,0))
        self.folder_listbox = tk.Listbox(folders_frame, height=8, background="#EAEAEA", foreground="black", borderwidth=0, highlightthickness=0, selectbackground="#3478C5", selectforeground="white")
        self.folder_listbox.pack(padx=10, pady=5, fill="both", expand=True)
        self.folder_listbox.bind("<<ListboxSelect>>", self.on_folder_select)
        list_btn_frame = ctk.CTkFrame(folders_frame, fg_color="transparent"); list_btn_frame.pack(pady=5)
        ctk.CTkButton(list_btn_frame, text="➕ Ajouter", command=self.add_folder).pack(side="left", padx=5)
        self.edit_btn = ctk.CTkButton(list_btn_frame, text="✏️ Modifier", state="disabled", command=self.edit_folder); self.edit_btn.pack(side="left", padx=5)
        self.remove_btn = ctk.CTkButton(list_btn_frame, text="🗑️ Supprimer", state="disabled", command=self.remove_folder); self.remove_btn.pack(side="left", padx=5)

    def setup_log_panel(self):
        log_frame = ctk.CTkFrame(self.main_frame); log_frame.grid(row=3, column=0, padx=10, pady=10, sticky="nsew")
        log_frame.grid_columnconfigure(0, weight=1); log_frame.grid_rowconfigure(1, weight=1)
        title_frame = ctk.CTkFrame(log_frame, fg_color="transparent"); title_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(5,0))
        title_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(title_frame, text="Journal d'événements", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(title_frame, text="📂 Ouvrir Logs", width=120, command=self.open_log_folder, fg_color="transparent", border_width=1, text_color=("gray10", "gray90")).grid(row=0, column=1, sticky="e")
        self.log_textbox = ctk.CTkTextbox(log_frame, state="disabled", font=("Courier New", 12)); self.log_textbox.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.setup_logging()

    def setup_logging(self):
        self.log_queue = queue.Queue()
        class CTkTextboxHandler(logging.Handler):
            def __init__(self, queue): super().__init__(); self.queue = queue; self.setLevel(logging.INFO)
            def emit(self, record): self.queue.put(self.format(record))
        file_handler = logging.FileHandler(LOG_FILE, 'a', 'utf-8'); file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.textbox_handler = CTkTextboxHandler(self.log_queue); self.textbox_handler.setFormatter(logging.Formatter('%(message)s'))
        logger = logging.getLogger()
        if not logger.handlers: logger.setLevel(logging.INFO); logger.addHandler(file_handler); logger.addHandler(self.textbox_handler)
        self.process_log_queue()

    def process_log_queue(self):
        try:
            while True:
                record = self.log_queue.get_nowait()
                self.log_textbox.configure(state="normal"); self.log_textbox.insert("end", f"[{time.strftime('%H:%M:%S')}] {record}\n")
                self.log_textbox.configure(state="disabled"); self.log_textbox.see("end")
        except queue.Empty: pass
        finally: self.after(100, self.process_log_queue)

    def log(self, msg, level="info"): logging.info(msg) if level == "info" else logging.error(msg)
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try: return json.load(open(CONFIG_FILE, 'r')).get("monitored_configs", [])
            except (json.JSONDecodeError, AttributeError): return []
        return []
    def save_config(self):
        with open(CONFIG_FILE, 'w') as f: json.dump({"monitored_configs": self.monitored_configs}, f, indent=4)
        self.log("Configuration sauvegardée.")

    def update_folder_listbox(self):
        self.folder_listbox.delete(0, tk.END)
        for config in self.monitored_configs: self.folder_listbox.insert(tk.END, f" {config['path']}")
        self.on_folder_select(None)

    def on_folder_select(self, event):
        state = "normal" if self.folder_listbox.curselection() else "disabled"
        self.edit_btn.configure(state=state); self.remove_btn.configure(state=state)

    def add_folder(self):
        dialog = FolderSettingsDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            if any(c['path'] == dialog.result['path'] for c in self.monitored_configs): messagebox.showerror("Erreur", "Ce dossier est déjà surveillé."); return
            self.monitored_configs.append(dialog.result); self.update_folder_listbox()
            self.log(f"Nouvelle règle ajoutée pour : {dialog.result['path']}")
    
    def edit_folder(self):
        idx = self.folder_listbox.curselection()
        if not idx: return
        dialog = FolderSettingsDialog(self, config=self.monitored_configs[idx[0]])
        self.wait_window(dialog)
        if dialog.result:
            self.monitored_configs[idx[0]] = dialog.result; self.update_folder_listbox()
            self.log(f"Règle modifiée pour : {dialog.result['path']}")

    def remove_folder(self):
        idx = self.folder_listbox.curselection()
        if not idx: return
        path = self.monitored_configs[idx[0]]['path']
        if messagebox.askyesno("Confirmation", f"Supprimer la règle pour\n{path} ?"):
            del self.monitored_configs[idx[0]]; self.update_folder_listbox()
            self.log(f"Règle de surveillance supprimée pour : {path}")

    def start_surveillance(self):
        if not self.monitored_configs: messagebox.showwarning("Aucune règle", "Veuillez ajouter un dossier à surveiller."); return
        configs_map = {config['path']: config for config in self.monitored_configs}
        self.worker_thread = OCRWatcher(configs_map, self.log_queue); self.worker_thread.start()
        self.start_button.configure(state="disabled"); self.stop_button.configure(state="normal")
    
    def stop_surveillance(self):
        if self.worker_thread: self.worker_thread.stop()
        self.start_button.configure(state="normal"); self.stop_button.configure(state="disabled")

    def open_log_folder(self):
        self.log(f"Ouverture du dossier des logs : {LOG_DIR}")
        if IS_WINDOWS: os.startfile(LOG_DIR)
        else: subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", LOG_DIR])

    def on_closing(self):
        self.save_config()
        if self.worker_thread and self.worker_thread.is_alive():
            self.stop_surveillance(); self.worker_thread.join(timeout=2)
        self.destroy()

    def update_startup_setting(self):
        if not IS_WINDOWS: return
        if self.startup_check.get(): self.add_to_startup()
        else: self.remove_from_startup()

    def get_exe_path(self):
        if getattr(sys, 'frozen', False): return sys.executable
        return os.path.abspath(sys.argv[0])

    def add_to_startup(self):
        if not IS_WINDOWS: return
        try:
            key = winreg.HKEY_CURRENT_USER; subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE) as reg_key: winreg.SetValueEx(reg_key, APP_NAME, 0, winreg.REG_SZ, self.get_exe_path())
            self.log("Ajouté au démarrage de Windows.")
        except Exception as e: self.log(f"Erreur d'ajout au démarrage : {e}", "error")

    def remove_from_startup(self):
        if not IS_WINDOWS: return
        try:
            key = winreg.HKEY_CURRENT_USER; subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, subkey, 0, winreg.KEY_WRITE) as reg_key: winreg.DeleteValue(reg_key, APP_NAME)
            self.log("Retiré du démarrage de Windows.")
        except FileNotFoundError: pass
        except Exception as e: self.log(f"Erreur de suppression du démarrage : {e}", "error")

    def is_in_startup(self):
        if not IS_WINDOWS: return False
        try:
            key = winreg.HKEY_CURRENT_USER; subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, subkey, 0, winreg.KEY_READ) as reg_key: winreg.QueryValueEx(reg_key, APP_NAME)
            return True
        except FileNotFoundError: return False

if __name__ == "__main__":
    app = App()
    app.mainloop()

# --- FIN DE LA PARTIE 2/2 ---