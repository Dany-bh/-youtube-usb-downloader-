import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import scrolledtext
import threading
import os
import shutil
import tempfile
import ctypes
import string
import re
import sys
import subprocess
import queue
import yt_dlp
import json
from tkinter import filedialog

# Color palette & font styles for custom dark design system
STYLE = {
    "bg": "#0F172A",            # Deep dark background (Slate-900)
    "card_bg": "#1E293B",       # Container cards (Slate-800)
    "input_bg": "#0F172A",      # Inputs / Console (Slate-900)
    "fg": "#F8FAFC",            # Primary text (Slate-50)
    "fg_muted": "#94A3B8",      # Secondary text (Slate-400)
    "accent_green": "#10B981",  # Primary download actions (Emerald-500)
    "accent_green_hover": "#059669",
    "accent_blue": "#3B82F6",   # Secondary actions (Blue-500)
    "accent_blue_hover": "#2563EB",
    "border": "#475569",        # Borders & lines (Slate-600)
    "border_light": "#334155",  # Subtle separators (Slate-700)
    "error": "#EF4444",         # Red for warnings/errors (Red-500)
    "font_title": ("Segoe UI", 16, "bold"),
    "font_subtitle": ("Segoe UI", 9, "italic"),
    "font_header": ("Segoe UI", 11, "bold"),
    "font_body": ("Segoe UI", 10),
    "font_bold": ("Segoe UI", 10, "bold"),
    "font_mono": ("Consolas", 9)
}

def get_volume_label(drive_path):
    """Retrieve the volume label of a drive on Windows using ctypes."""
    volumeNameBuffer = ctypes.create_unicode_buffer(1024)
    fileSystemNameBuffer = ctypes.create_unicode_buffer(1024)
    serial_number = ctypes.c_ulong(0)
    max_component_length = ctypes.c_ulong(0)
    file_system_flags = ctypes.c_ulong(0)
    
    rc = ctypes.windll.kernel32.GetVolumeInformationW(
        drive_path,
        volumeNameBuffer,
        len(volumeNameBuffer),
        ctypes.byref(serial_number),
        ctypes.byref(max_component_length),
        ctypes.byref(file_system_flags),
        fileSystemNameBuffer,
        len(fileSystemNameBuffer)
    )
    if rc:
        return volumeNameBuffer.value
    return ""

def get_usb_drives():
    """Scan the system for removable USB drives using Windows API."""
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in string.ascii_uppercase:
        if bitmask & 1:
            drive_path = f"{letter}:\\"
            # GetDriveTypeW return value 2 means DRIVE_REMOVABLE (USB flash drives)
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
            if drive_type == 2:
                try:
                    usage = shutil.disk_usage(drive_path)
                    free_gb = usage.free / (1024 ** 3)
                    total_gb = usage.total / (1024 ** 3)
                    label = get_volume_label(drive_path)
                    name = f"Unidad {letter} ({label})" if label else f"Unidad {letter}"
                    drives.append({
                        'path': drive_path,
                        'display': f"{name} - {free_gb:.2f} GB libres de {total_gb:.2f} GB",
                        'free_bytes': usage.free
                    })
                except Exception:
                    # In case the USB drive is inserted but unformatted or inaccessible
                    drives.append({
                        'path': drive_path,
                        'display': f"Unidad {letter}:\\ (No disponible o sin formato)",
                        'free_bytes': 0
                    })
        bitmask >>= 1
    return drives

def sanitize_filename(name):
    """Sanitize video titles to make them safe for Windows filesystem."""
    cleaned = re.sub(r'[\\/*?:"<>|]', '', name)
    cleaned = cleaned.strip().strip('.')
    if not cleaned:
        cleaned = "audio_youtube"
    return cleaned[:150]  # Limit path length to prevent Windows MAX_PATH errors

class PlaceholderEntry(tk.Entry):
    """An Entry widget with placeholder text that disappears when focused."""
    def __init__(self, parent, placeholder, **kwargs):
        self.placeholder = placeholder
        self.placeholder_color = STYLE["fg_muted"]
        self.default_fg_color = STYLE["fg"]
        super().__init__(parent, fg=self.placeholder_color, bg=STYLE["input_bg"],
                         insertbackground=STYLE["fg"], relief="flat", bd=0, 
                         highlightthickness=1, highlightbackground=STYLE["border"],
                         highlightcolor=STYLE["accent_blue"], **kwargs)
        self.insert(0, self.placeholder)
        self.bind("<FocusIn>", self._focus_in)
        self.bind("<FocusOut>", self._focus_out)

    def _focus_in(self, event):
        if self.get() == self.placeholder:
            self.delete(0, tk.END)
            self.config(fg=self.default_fg_color)

    def _focus_out(self, event):
        if not self.get():
            self.insert(0, self.placeholder)
            self.config(fg=self.placeholder_color)
            
    def get_actual_text(self):
        val = self.get()
        if val == self.placeholder:
            return ""
        return val.strip()
        
    def set_text(self, text):
        self.delete(0, tk.END)
        self.insert(0, text)
        self.config(fg=self.default_fg_color)

class ModernButton(tk.Button):
    """A flat button styled consistently with hover states and disabled states."""
    def __init__(self, parent, text, bg_color, hover_color, command=None, fg_color=STYLE["fg"], **kwargs):
        super().__init__(
            parent,
            text=text,
            bg=bg_color,
            fg=fg_color,
            activebackground=hover_color,
            activeforeground=fg_color,
            bd=0,
            relief="flat",
            font=STYLE["font_bold"],
            cursor="hand2",
            padx=12,
            pady=6,
            command=command,
            **kwargs
        )
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.bind("<Enter>", self.on_enter)
        self.bind("<Leave>", self.on_leave)
        
    def on_enter(self, event):
        if str(self["state"]) != "disabled":
            self.config(bg=self.hover_color)
            
    def on_leave(self, event):
        if str(self["state"]) != "disabled":
            self.config(bg=self.bg_color)
            
    def set_disabled(self, disabled=True):
        if disabled:
            self.config(state="disabled", bg=STYLE["border_light"], fg=STYLE["fg_muted"])
        else:
            self.config(state="normal", bg=self.bg_color, fg=STYLE["fg"])

class ModernProgressBar(tk.Canvas):
    """A beautiful, custom drawn flat progress bar."""
    def __init__(self, parent, bg, fill_color, border_color, height=18, **kwargs):
        super().__init__(parent, bg=bg, height=height, bd=0, highlightthickness=0, **kwargs)
        self.fill_color = fill_color
        self.bg_color = bg
        self.border_color = border_color
        self.progress = 0.0
        self.bind("<Configure>", self.draw)
        
    def set_progress(self, value):
        self.progress = max(0.0, min(100.0, float(value)))
        self.draw()
        
    def draw(self, event=None):
        self.delete("all")
        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1:
            return # Canvas not yet fully rendered
            
        # Draw background track
        self.create_rectangle(0, 0, width, height, fill=self.bg_color, outline=self.border_color, width=1)
        
        # Draw filled part
        if self.progress > 0:
            fill_width = int((self.progress / 100.0) * width)
            # Clip width to canvas boundary
            fill_width = min(fill_width, width)
            self.create_rectangle(0, 0, fill_width, height, fill=self.fill_color, outline="", width=0)

class YTDLPLogger:
    """Redirects yt-dlp logs directly into our custom GUI Console widget."""
    def __init__(self, app):
        self.app = app
        
    def debug(self, msg):
        # Clean up output formatting for readability
        if msg.strip():
            self.app.run_in_gui_thread(self.app.log_message, f"[INFO] {msg}\n")
            
    def info(self, msg):
        if msg.strip():
            self.app.run_in_gui_thread(self.app.log_message, f"[INFO] {msg}\n")
            
    def warning(self, msg):
        if msg.strip():
            self.app.run_in_gui_thread(self.app.log_message, f"[WARN] {msg}\n", is_error=True)
            
    def error(self, msg):
        if msg.strip():
            self.app.run_in_gui_thread(self.app.log_message, f"[ERROR] {msg}\n", is_error=True)

class YouTubeUSBApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube USB Audio Downloader")
        self.root.geometry("760x640")
        self.root.minsize(700, 580)
        self.root.configure(bg=STYLE["bg"])
        
        # Setup application-wide styles for Ttk combobox and lists
        self.setup_combobox_styles()
        
        # Thread safety communication queue
        self.gui_queue = queue.Queue()
        self.root.after(100, self.process_gui_queue)
        
        # Application state variables
        self.ui_state = "ready" # ready | busy
        self.usb_combobox_focused = False
        self.last_scanned_drives = []
        self.scanned_drives_data = [] # Stores full dictionary lists
        
        # Load persistent download destination path
        self.selected_path = self.load_config()
        
        # UI setup
        self.create_widgets()
        
        # Initial USB scanning & start automatic detection loop
        self.refresh_usb_drives()
        self.root.after(5000, self.auto_scan_usbs)
        
        # Diagnostics
        self.check_ffmpeg_dependency()

    def setup_combobox_styles(self):
        """Configure ttk styles to make comboboxes fit our custom dark theme."""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Style the dropdown entry field
        style.configure('TCombobox',
                        fieldbackground=STYLE["input_bg"],
                        background=STYLE["card_bg"],
                        foreground=STYLE["fg"],
                        bordercolor=STYLE["border"],
                        arrowcolor=STYLE["fg"])
                        
        # Register option database styles to color the actual pop-up Listbox inside combobox
        self.root.option_add('*TCombobox*Listbox.background', STYLE["card_bg"])
        self.root.option_add('*TCombobox*Listbox.foreground', STYLE["fg"])
        self.root.option_add('*TCombobox*Listbox.selectBackground', STYLE["accent_blue"])
        self.root.option_add('*TCombobox*Listbox.selectForeground', STYLE["fg"])
        self.root.option_add('*TCombobox*Listbox.relief', 'flat')
        self.root.option_add('*TCombobox*Listbox.font', STYLE["font_body"])

    def create_widgets(self):
        """Assemble all sections of the application."""
        # Top spacing
        lbl_pad = tk.Label(self.root, bg=STYLE["bg"])
        lbl_pad.pack(pady=4)
        
        # 1. HEADER BANNER
        header_frame = tk.Frame(self.root, bg=STYLE["bg"])
        header_frame.pack(fill="x", padx=25, pady=(0, 15))
        
        title_label = tk.Label(header_frame, text="YouTube USB Audio Downloader", 
                               font=STYLE["font_title"], fg=STYLE["fg"], bg=STYLE["bg"])
        title_label.pack(anchor="w")
        
        subtitle_label = tk.Label(header_frame, 
                                  text="Descarga y conversión legal y autorizada de audio directamente a memorias USB.",
                                  font=STYLE["font_subtitle"], fg=STYLE["fg_muted"], bg=STYLE["bg"])
        subtitle_label.pack(anchor="w", pady=(2, 0))
        
        # 2. MAIN WORKSPACE FRAME (Card Design)
        self.card = tk.Frame(self.root, bg=STYLE["card_bg"], 
                             highlightbackground=STYLE["border_light"], highlightthickness=1, bd=0)
        # Note: self.card will be packed at the very end of create_widgets
        # to prevent it from pushing the footer actions off-screen.
        
        # Step 1 Section: Video Link Input
        s1_frame = tk.Frame(self.card, bg=STYLE["card_bg"])
        s1_frame.pack(fill="x", padx=20, pady=(20, 10))
        
        s1_lbl = tk.Label(s1_frame, text="Paso 1: Pegar enlace de YouTube", 
                          font=STYLE["font_header"], fg=STYLE["accent_blue"], bg=STYLE["card_bg"])
        s1_lbl.pack(anchor="w")
        
        input_container = tk.Frame(s1_frame, bg=STYLE["card_bg"])
        input_container.pack(fill="x", pady=(5, 5))
        
        self.url_entry = PlaceholderEntry(input_container, "https://www.youtube.com/watch?v=...", font=STYLE["font_body"])
        self.url_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        self.url_entry.bind("<KeyRelease>", self.on_url_key_release)
        
        self.btn_paste = ModernButton(input_container, "Pegar Link", STYLE["accent_blue"], STYLE["accent_blue_hover"], 
                                      command=self.paste_url)
        self.btn_paste.pack(side="right")
        
        # Video Metadata Preview Frame
        self.meta_frame = tk.Frame(s1_frame, bg=STYLE["input_bg"], highlightbackground=STYLE["border_light"], 
                                   highlightthickness=1, bd=0)
        self.meta_frame.pack(fill="x", pady=(5, 0))
        self.meta_lbl = tk.Label(self.meta_frame, 
                                 text="Ingresa un enlace para ver los detalles del video...", 
                                 font=STYLE["font_subtitle"], fg=STYLE["fg_muted"], bg=STYLE["input_bg"],
                                 padx=12, pady=8)
        self.meta_lbl.pack(anchor="w")
        
        # Step 2 Section: USB Destination Select (USB or Folder)
        s2_frame = tk.Frame(self.card, bg=STYLE["card_bg"])
        s2_frame.pack(fill="x", padx=20, pady=10)
        
        s2_lbl = tk.Label(s2_frame, text="Paso 2: Destino de la descarga (USB o Carpeta)", 
                          font=STYLE["font_header"], fg=STYLE["accent_blue"], bg=STYLE["card_bg"])
        s2_lbl.pack(anchor="w")
        
        usb_container = tk.Frame(s2_frame, bg=STYLE["card_bg"])
        usb_container.pack(fill="x", pady=(5, 0))
        
        self.usb_combobox = ttk.Combobox(usb_container, state="readonly", font=STYLE["font_body"])
        self.usb_combobox.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))
        self.usb_combobox.bind("<FocusIn>", lambda e: self.set_usb_focus(True))
        self.usb_combobox.bind("<FocusOut>", lambda e: self.set_usb_focus(False))
        self.usb_combobox.bind("<<ComboboxSelected>>", self.on_usb_selected)
        
        self.btn_browse = ModernButton(usb_container, "Examinar...", STYLE["accent_blue"], STYLE["accent_blue_hover"],
                                       command=self.browse_custom_directory)
        self.btn_browse.pack(side="right", padx=(8, 0))
        
        self.btn_refresh_usb = ModernButton(usb_container, "Actualizar", STYLE["accent_blue"], STYLE["accent_blue_hover"], 
                                            command=self.refresh_usb_drives)
        self.btn_refresh_usb.pack(side="right")
        
        # Step 3 Section: Consent & Policy Checkbox
        s3_frame = tk.Frame(self.card, bg=STYLE["card_bg"])
        s3_frame.pack(fill="x", padx=20, pady=10)
        
        s3_lbl = tk.Label(s3_frame, text="Paso 3: Autorización Legal", 
                          font=STYLE["font_header"], fg=STYLE["accent_blue"], bg=STYLE["card_bg"])
        s3_lbl.pack(anchor="w")
        
        self.consent_var = tk.BooleanVar(value=False)
        self.chk_consent = tk.Checkbutton(
            s3_frame,
            text="Confirmo que tengo los derechos de propiedad intelectual, licencia, o la expresa autorización\n"
                 "del titular de los derechos de autor para descargar el audio de este video.",
            variable=self.consent_var,
            bg=STYLE["card_bg"],
            fg=STYLE["fg_muted"],
            activebackground=STYLE["card_bg"],
            activeforeground=STYLE["fg"],
            selectcolor=STYLE["input_bg"],
            font=STYLE["font_body"],
            justify="left",
            anchor="w",
            command=self.toggle_download_button,
            cursor="hand2"
        )
        self.chk_consent.pack(anchor="w", pady=(5, 0))
        
        # Step 4 Section: Live Output Console & Progress Monitoring
        s4_frame = tk.Frame(self.card, bg=STYLE["card_bg"])
        s4_frame.pack(fill="both", expand=True, padx=20, pady=(10, 15))
        
        self.progress_lbl = tk.Label(s4_frame, text="Listo", font=STYLE["font_bold"], fg=STYLE["fg"], bg=STYLE["card_bg"])
        self.progress_lbl.pack(anchor="w")
        
        self.progress_details = tk.Label(s4_frame, text="Estadísticas de descarga no iniciadas", 
                                         font=STYLE["font_subtitle"], fg=STYLE["fg_muted"], bg=STYLE["card_bg"])
        self.progress_details.pack(anchor="w", pady=(0, 5))
        
        self.progress_bar = ModernProgressBar(s4_frame, bg=STYLE["input_bg"], fill_color=STYLE["accent_green"], 
                                              border_color=STYLE["border_light"])
        self.progress_bar.pack(fill="x", pady=(0, 10))
        
        # Embedded scrolling log console
        console_lbl = tk.Label(s4_frame, text="Consola de descarga en vivo:", font=STYLE["font_subtitle"], 
                               fg=STYLE["fg_muted"], bg=STYLE["card_bg"])
        console_lbl.pack(anchor="w", pady=(0, 2))
        
        self.console = scrolledtext.ScrolledText(
            s4_frame,
            bg=STYLE["input_bg"],
            fg=STYLE["fg_muted"],
            insertbackground=STYLE["fg"],
            font=STYLE["font_mono"],
            relief="flat",
            bd=0,
            height=6,
            state="disabled",
            highlightthickness=1,
            highlightbackground=STYLE["border_light"]
        )
        self.console.pack(fill="both", expand=True)
        self.console.tag_config("error", foreground=STYLE["error"])
        
        # 3. CONTROL FOOTER ACTIONS
        footer_frame = tk.Frame(self.root, bg=STYLE["bg"])
        footer_frame.pack(side="bottom", fill="x", padx=25, pady=(0, 20))
        
        # Missing ffmpeg error panel (if applicable)
        self.ffmpeg_warn_label = tk.Label(footer_frame, text="", font=STYLE["font_bold"], fg=STYLE["error"], 
                                          bg=STYLE["bg"], anchor="w")
        self.ffmpeg_warn_label.pack(side="left")
        
        # Action triggers
        button_container = tk.Frame(footer_frame, bg=STYLE["bg"])
        button_container.pack(side="right")
        
        self.btn_update = ModernButton(button_container, "Actualizar yt-dlp", STYLE["input_bg"], STYLE["card_bg"],
                                       command=self.update_yt_dlp, highlightbackground=STYLE["border_light"],
                                       highlightthickness=1)
        self.btn_update.pack(side="left", padx=(0, 10))
        
        self.btn_download = ModernButton(button_container, "Descargar y Guardar en USB", STYLE["accent_green"], STYLE["accent_green_hover"], 
                                         command=self.start_download_process)
        self.btn_download.pack(side="right")
        
        # Now pack the main card to fill the remaining vertical space between header and footer
        self.card.pack(fill="both", expand=True, padx=25, pady=(0, 15))
        
        # Setup initial activation states
        self.toggle_download_button()

    # THREADING MANAGEMENT (Thread-safe Queue handlers)
    def run_in_gui_thread(self, callback, *args, **kwargs):
        """Add UI commands to run safely in the main tkinter thread loop."""
        self.gui_queue.put((callback, args, kwargs))
        
    def process_gui_queue(self):
        """Periodically run queued events on the main GUI thread."""
        try:
            while True:
                callback, args, kwargs = self.gui_queue.get_nowait()
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    print(f"Error executing GUI thread callback: {e}")
                self.gui_queue.task_done()
        except queue.Empty:
            pass
        self.root.after(100, self.process_gui_queue)

    # EVENT MONITORING AND CONTROL STATE MANAGEMENT
    def on_url_key_release(self, event):
        """Triggered as the user typing/pasting URLs. Performs lightweight async fetch."""
        # Simple debounce to avoid running multiple calls for unfinished pastes
        debounce_id = getattr(self, '_url_debounce_id', None)
        if debounce_id is not None:
            try:
                self.root.after_cancel(debounce_id)
            except Exception:
                pass
        self._url_debounce_id = self.root.after(800, self.trigger_async_metadata_fetch)
        
    def trigger_async_metadata_fetch(self):
        url = self.url_entry.get_actual_text()
        if not url:
            self.meta_lbl.config(text="Ingresa un enlace para ver los detalles del video...", fg=STYLE["fg_muted"])
            return
            
        if "youtube.com/" in url or "youtu.be/" in url:
            # Run metadata extraction in background
            threading.Thread(target=self.fetch_metadata_worker, args=(url,), daemon=True).start()
        else:
            self.meta_lbl.config(text="⚠️ Por favor, ingresa una URL de YouTube válida.", fg=STYLE["error"])

    def fetch_metadata_worker(self, url):
        """Worker thread to query basic video title/author before starting downloads."""
        self.run_in_gui_thread(self.meta_lbl.config, text="🔍 Consultando detalles del video en YouTube...", fg=STYLE["accent_blue"])
        try:
            ydl_opts = {
                'extract_flat': True,
                'skip_download': True,
                'noplaylist': True,
                'check_formats': False,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                # Verificar si el usuario cambió la URL mientras se hacía la consulta
                if self.url_entry.get_actual_text() != url:
                    return
                title = info.get('title', 'Título desconocido')
                uploader = info.get('uploader', 'Canal desconocido')
                duration_secs = info.get('duration')
                
                duration_str = ""
                if duration_secs:
                    mins, secs = divmod(int(duration_secs), 60)
                    duration_str = f" | Duración: {mins}m {secs}s"
                
                meta_text = f"🎵 {title}\nCanal: {uploader}{duration_str}"
                self.run_in_gui_thread(self.meta_lbl.config, text=meta_text, fg=STYLE["accent_green"])
        except Exception:
            # Evitar mostrar el mensaje de error si el usuario ya modificó la URL
            if self.url_entry.get_actual_text() == url:
                self.run_in_gui_thread(self.meta_lbl.config, text="⚠️ No se pudieron obtener los detalles de este video.", fg=STYLE["fg_muted"])

    def paste_url(self):
        """Paste system clipboard content into the input bar."""
        try:
            content = self.root.clipboard_get()
            self.url_entry.set_text(content)
            self.trigger_async_metadata_fetch()
        except Exception:
            self.log_message("[ADVERTENCIA] No hay texto disponible en el portapapeles.\n", is_error=True)

    def set_usb_focus(self, focused):
        self.usb_combobox_focused = focused

    def toggle_download_button(self):
        """Enable/disable actions based on UI states and legal checkbox."""
        if self.ui_state == "busy":
            self.btn_download.set_disabled(True)
            self.btn_paste.set_disabled(True)
            self.btn_refresh_usb.set_disabled(True)
            self.btn_browse.set_disabled(True)
            self.btn_update.set_disabled(True)
            self.url_entry.config(state="disabled")
            self.chk_consent.config(state="disabled")
        else:
            self.btn_paste.set_disabled(False)
            self.btn_refresh_usb.set_disabled(False)
            self.btn_browse.set_disabled(False)
            self.btn_update.set_disabled(False)
            self.url_entry.config(state="normal")
            self.chk_consent.config(state="normal")
            
            # Checkbox check condition
            if self.consent_var.get() and self.check_ffmpeg_dependency():
                self.btn_download.set_disabled(False)
            else:
                self.btn_download.set_disabled(True)

    # SUBPROCESS & DIAGNOSTIC TASKS
    def check_ffmpeg_dependency(self):
        """Verify FFmpeg is configured correctly on the Windows shell environment."""
        has_ffmpeg = shutil.which('ffmpeg') is not None
        if not has_ffmpeg:
            self.ffmpeg_warn_label.config(
                text="⚠️ FFmpeg no detectado. Instálalo para habilitar la conversión a MP3."
            )
            return False
        else:
            self.ffmpeg_warn_label.config(text="")
            return True

    def load_config(self):
        """Loads configuration from config.json, returning the saved path."""
        try:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    return config.get("download_path", "")
        except Exception:
            pass
        return ""

    def save_config(self, path):
        """Saves config dict with download_path key to config.json."""
        try:
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump({"download_path": path}, f, indent=4)
        except Exception:
            pass

    def on_usb_selected(self, event):
        """Callback when user selects an option in the destination combobox."""
        selected_index = self.usb_combobox.current()
        if 0 <= selected_index < len(self.scanned_drives_data):
            self.selected_path = self.scanned_drives_data[selected_index]['path']
            self.save_config(self.selected_path)
            self.log_message(f"[SISTEMA] Destino seleccionado: {self.selected_path}\n")

    def browse_custom_directory(self):
        """Opens a directory chooser to select a custom destination path."""
        if self.ui_state == "busy":
            return
            
        initial_dir = self.selected_path if os.path.exists(self.selected_path) else os.path.expanduser("~")
        path = filedialog.askdirectory(parent=self.root, title="Seleccionar Carpeta de Destino", initialdir=initial_dir)
        
        if path:
            path = os.path.abspath(path)
            self.selected_path = path
            self.save_config(self.selected_path)
            self.log_message(f"[SISTEMA] Carpeta personalizada elegida: {self.selected_path}\n")
            self.refresh_usb_drives()

    def get_all_destinations(self):
        """Scans the system for USB drives and appends the custom saved path if applicable."""
        drives = get_usb_drives()
        if self.selected_path:
            norm_selected = os.path.abspath(self.selected_path).lower().rstrip(os.sep)
            already_exists = False
            for d in drives:
                norm_d = os.path.abspath(d['path']).lower().rstrip(os.sep)
                if norm_d == norm_selected:
                    already_exists = True
                    break
            if not already_exists:
                try:
                    usage = shutil.disk_usage(self.selected_path)
                    free_gb = usage.free / (1024 ** 3)
                    total_gb = usage.total / (1024 ** 3)
                    display = f"Carpeta: {self.selected_path} - {free_gb:.2f} GB libres de {total_gb:.2f} GB"
                    drives.append({
                        'path': self.selected_path,
                        'display': display,
                        'free_bytes': usage.free
                    })
                except Exception:
                    drives.append({
                        'path': self.selected_path,
                        'display': f"Carpeta: {self.selected_path} (No disponible)",
                        'free_bytes': 0
                    })
        return drives

    def refresh_usb_drives(self):
        """Scans the physical ports for USB removable filesystems and populates the combobox."""
        if self.ui_state == "busy":
            return
            
        drives = self.get_all_destinations()
        self.update_usb_dropdown(drives)
        self.log_message(f"[SISTEMA] Detección de puertos: {len(drives)} unidades/carpetas encontradas.\n")

    def update_usb_dropdown(self, drives_list):
        """Update combobox dataset and restore the active selection based on self.selected_path."""
        self.scanned_drives_data = drives_list
        displays = [d['display'] for d in drives_list]
        self.last_scanned_drives = displays
        
        self.usb_combobox['values'] = displays
        
        # Find if our self.selected_path is in the drives_list
        selected_index = -1
        if self.selected_path:
            norm_selected = os.path.abspath(self.selected_path).lower().rstrip(os.sep)
            for i, d in enumerate(drives_list):
                norm_d = os.path.abspath(d['path']).lower().rstrip(os.sep)
                if norm_d == norm_selected:
                    selected_index = i
                    break
                
        if selected_index != -1:
            self.usb_combobox.set(displays[selected_index])
        elif displays:
            # If our selected path isn't found and we have options, select the first one
            self.usb_combobox.set(displays[0])
            self.selected_path = drives_list[0]['path']
            self.save_config(self.selected_path)
        else:
            self.usb_combobox.set("--- No se detectaron memorias USB o carpetas ---")
            self.selected_path = ""

    def auto_scan_usbs(self):
        """Periodically runs background scans for hotplugged USB drives."""
        if self.ui_state == "ready" and not self.usb_combobox_focused:
            drives = self.get_all_destinations()
            displays = [d['display'] for d in drives]
            if displays != self.last_scanned_drives:
                self.update_usb_dropdown(drives)
        self.root.after(5000, self.auto_scan_usbs)

    # LOGGING UTILITY
    def log_message(self, text, is_error=False):
        """Appends logs to the live scrolling UI console textbox with a line limit."""
        self.console.config(state="normal")
        if is_error:
            self.console.insert(tk.END, text, "error")
        else:
            self.console.insert(tk.END, text)
            
        # Limitar la consola a las últimas 500 líneas para optimizar rendimiento de Tkinter
        try:
            total_lines = int(self.console.index('end-1c').split('.')[0])
            if total_lines > 500:
                self.console.delete("1.0", f"{total_lines - 500}.0")
        except Exception:
            pass
            
        self.console.see(tk.END)
        self.console.config(state="disabled")

    # BACKGROUND WORKER STARTUP
    def start_download_process(self):
        """Validador general antes de disparar el hilo background de descarga."""
        url = self.url_entry.get_actual_text()
        if not url or url.startswith("https://www.youtube.com/watch?v=..."):
            messagebox.showerror("Error de entrada", "Por favor, introduce un enlace de YouTube válido.")
            return
            
        if not self.scanned_drives_data:
            messagebox.showerror("Sin destino seleccionado", "No se ha seleccionado ningún destino de descarga. Conecte un USB o elija una carpeta.")
            return
            
        selected_index = self.usb_combobox.current()
        if selected_index < 0 or selected_index >= len(self.scanned_drives_data):
            messagebox.showerror("Selección inválida", "Por favor, seleccione un destino de descarga válido de la lista.")
            return
            
        selected_usb = self.scanned_drives_data[selected_index]
        if selected_usb['free_bytes'] == 0:
            messagebox.showerror("Destino insuficiente o inaccesible", f"La ruta {selected_usb['path']} no tiene espacio suficiente o no es accesible.")
            return

        # Start thread
        self.ui_state = "busy"
        self.toggle_download_button()
        
        # Clear progress bar
        self.progress_bar.set_progress(0)
        self.progress_lbl.config(text="Preparando descarga...", fg=STYLE["fg"])
        self.progress_details.config(text="Inicializando motores de extracción...")
        
        # Fire background task
        threading.Thread(
            target=self.download_and_copy_thread_worker, 
            args=(url, selected_usb), 
            daemon=True
        ).start()

    def cleanup_temp_files(self, temp_dir, temp_file_base):
        """Removes any temporary files created by yt-dlp/ffmpeg matching the base name."""
        try:
            for filename in os.listdir(temp_dir):
                if filename.startswith(temp_file_base):
                    try:
                        os.remove(os.path.join(temp_dir, filename))
                    except Exception:
                        pass
        except Exception:
            pass

    # CORE OPERATION: DOWNLOAD AND COPY THREAD WORKER
    def download_and_copy_thread_worker(self, url, usb_info):
        usb_path = usb_info['path']
        self.run_in_gui_thread(self.log_message, f"\n[INICIO] Iniciando descarga para enlace: {url}\n")
        self.run_in_gui_thread(self.log_message, f"[SISTEMA] Ruta de destino USB: {usb_path}\n")

        temp_dir = tempfile.gettempdir()
        video_id = ""
        title = "audio_youtube"
        
        # 1. Fetch exact Title and Video ID
        try:
            self.run_in_gui_thread(self.update_progress_ui, 0, "Conectando con YouTube...", "Extrayendo información del video...")
            ydl_opts_meta = {
                'noplaylist': True,
                'check_formats': False,
            }
            with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
                info = ydl.extract_info(url, download=False)
                video_id = info.get('id', 'temp_id')
                title = info.get('title', 'audio_youtube')
                self.run_in_gui_thread(self.log_message, f"[VIDEO] Título: {title}\n")
        except Exception as e:
            error_line = str(e).splitlines()[0]
            self.run_in_gui_thread(self.log_message, f"[ERROR] Extracción de metadatos fallida: {error_line}\n", is_error=True)
            self.run_in_gui_thread(messagebox.showerror, "Error de Conexión", 
                                   f"No se pudo conectar a YouTube o la URL no es válida.\n\nDetalle: {error_line}")
            self.cleanup_and_release_gui()
            return

        # Prepare filenames
        temp_file_base = f"yt_audio_{video_id}"
        local_mp3_path = os.path.join(temp_dir, f"{temp_file_base}.mp3")
        
        # Remove any lingering files from previous runs
        self.cleanup_temp_files(temp_dir, temp_file_base)

        # Options for extraction
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(temp_dir, f"{temp_file_base}.%(ext)s"),
            'noplaylist': True,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'progress_hooks': [self.yt_dlp_progress_hook],
            'postprocessor_hooks': [self.yt_dlp_postprocessor_hook],
            'logger': YTDLPLogger(self),
            'restrictfilenames': True,
            'concurrent_fragment_downloads': 8,
            'check_formats': False,
        }

        # 2. Start Downloader
        try:
            self.run_in_gui_thread(self.log_message, "[DESCARGA] Descargando flujo de audio desde YouTube...\n")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            error_line = str(e).splitlines()[0]
            self.run_in_gui_thread(self.log_message, f"[ERROR] Descarga/Conversión fallida: {error_line}\n", is_error=True)
            self.run_in_gui_thread(messagebox.showerror, "Error en descarga", 
                                   f"El descargador falló al obtener el audio.\n\nDetalle: {error_line}")
            # Ensure local trash clean up
            self.cleanup_temp_files(temp_dir, temp_file_base)
            self.cleanup_and_release_gui()
            return

        # Confirm MP3 exists locally
        if not os.path.exists(local_mp3_path):
            self.run_in_gui_thread(self.log_message, "[ERROR] Archivo MP3 no generado por FFmpeg.\n", is_error=True)
            self.run_in_gui_thread(messagebox.showerror, "Error de conversión", 
                                   "El audio se descargó, pero la conversión a MP3 falló.\nVerifique la instalación de FFmpeg.")
            self.cleanup_temp_files(temp_dir, temp_file_base)
            self.cleanup_and_release_gui()
            return

        # 3. Size and Space Verifications
        file_size_bytes = os.path.getsize(local_mp3_path)
        file_size_mb = file_size_bytes / (1024 * 1024)
        self.run_in_gui_thread(self.log_message, f"[SISTEMA] Archivo MP3 generado ({file_size_mb:.2f} MB).\n")
        
        try:
            # Refresh USB drive space details to make sure it's accurate
            usage = shutil.disk_usage(usb_path)
            self.run_in_gui_thread(self.log_message, f"[SISTEMA] Espacio libre en USB: {usage.free / (1024*1024):.2f} MB\n")
            
            if usage.free < file_size_bytes:
                raise ValueError("Espacio libre insuficiente en la memoria USB de destino.")
        except Exception as e:
            self.run_in_gui_thread(self.log_message, f"[ERROR] Espacio en USB inválido: {str(e)}\n", is_error=True)
            self.run_in_gui_thread(messagebox.showerror, "Espacio Insuficiente", 
                                   f"No hay espacio suficiente en el USB.\nNecesario: {file_size_mb:.2f} MB\nDisponible: {usage.free / (1024*1024):.2f} MB")
            self.cleanup_temp_files(temp_dir, temp_file_base)
            self.cleanup_and_release_gui()
            return

        # 4. Copy to USB
        sanitized_title = sanitize_filename(title)
        dest_filename = f"{sanitized_title}.mp3"
        dest_path = os.path.join(usb_path, dest_filename)
        
        # Append identifier index in case of collision to prevent overwrites
        counter = 1
        while os.path.exists(dest_path):
            dest_filename = f"{sanitized_title} ({counter}).mp3"
            dest_path = os.path.join(usb_path, dest_filename)
            counter += 1

        try:
            self.run_in_gui_thread(self.log_message, f"[SISTEMA] Copiando audio convertido a la memoria USB...\n")
            self.copy_file_to_usb_with_progress(local_mp3_path, dest_path)
            self.run_in_gui_thread(self.log_message, f"[SISTEMA] Archivo guardado correctamente en: {dest_path}\n")
        except Exception as e:
            self.run_in_gui_thread(self.log_message, f"[ERROR] Escritura en USB fallida: {str(e)}\n", is_error=True)
            self.run_in_gui_thread(messagebox.showerror, "Error de copia", 
                                   f"No se pudo copiar el archivo al dispositivo USB.\n\nDetalle: {str(e)}")
            self.cleanup_temp_files(temp_dir, temp_file_base)
            self.cleanup_and_release_gui()
            return

        # 5. Clean up local temp file
        self.run_in_gui_thread(self.log_message, "[SISTEMA] Limpiando archivos temporales locales...\n")
        self.cleanup_temp_files(temp_dir, temp_file_base)

        # 6. Final success
        self.run_in_gui_thread(self.log_message, "[ÉXITO] Todo el proceso finalizó con éxito.\n")
        self.run_in_gui_thread(self.update_progress_ui, 100.0, "¡Conversión y copia completada!", f"Guardado como: {dest_filename}")
        self.run_in_gui_thread(messagebox.showinfo, "Éxito", 
                               f"El audio ha sido descargado, convertido a MP3 y copiado correctamente a su USB.\n\nNombre: {dest_filename}")
        
        # Reload USB data and restore UI
        self.run_in_gui_thread(self.refresh_usb_drives)
        self.cleanup_and_release_gui()

    def copy_file_to_usb_with_progress(self, src, dst):
        """Copies file to USB block-by-block and updates the GUI with progress."""
        total_size = os.path.getsize(src)
        copied_bytes = 0
        buffer_size = 512 * 1024  # 512KB chunks
        
        with open(src, 'rb') as fsrc:
            with open(dst, 'wb') as fdst:
                while True:
                    chunk = fsrc.read(buffer_size)
                    if not chunk:
                        break
                    fdst.write(chunk)
                    copied_bytes += len(chunk)
                    
                    percent = (copied_bytes / total_size * 100.0) if total_size > 0 else 0.0
                    copied_mb = copied_bytes / (1024 * 1024)
                    total_mb = total_size / (1024 * 1024)
                    
                    status_text = f"Copiando a USB: {percent:.1f}%"
                    details_text = f"Escribiendo {copied_mb:.1f} MB de {total_mb:.1f} MB..."
                    
                    self.run_in_gui_thread(self.update_progress_ui, percent, status_text, details_text)
                
                # Forzar la sincronización en el almacenamiento físico antes de cerrar el archivo
                self.run_in_gui_thread(self.update_progress_ui, 99.0, "Copiando a USB...", "Finalizando escritura y vaciando búfer físico...")
                fdst.flush()
                try:
                    os.fsync(fdst.fileno())
                except Exception:
                    pass

    # PROGRESS MONITOR HOOKS FROM YT-DLP
    def yt_dlp_progress_hook(self, d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            speed = d.get('speed', 0)
            eta = d.get('eta', 0)
            
            percent = (downloaded / total * 100.0) if total > 0 else 0.0
            
            # Format download speed indicator
            if speed:
                if speed > 1024 * 1024:
                    speed_str = f"{speed / (1024 * 1024):.2f} MB/s"
                else:
                    speed_str = f"{speed / 1024:.2f} KB/s"
            else:
                speed_str = "Calculando..."
                
            # Format download ETA
            if eta:
                mins, secs = divmod(int(eta), 60)
                eta_str = f"{mins}m {secs}s"
            else:
                eta_str = "--"
                
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            
            status_text = f"Descargando audio: {percent:.1f}%"
            details_text = f"{dl_mb:.1f} MB de {tot_mb:.1f} MB | Vel: {speed_str} | ETA: {eta_str}"
            
            self.run_in_gui_thread(self.update_progress_ui, percent, status_text, details_text)
            
        elif d['status'] == 'finished':
            self.run_in_gui_thread(self.update_progress_ui, 100.0, "Descarga de flujo completada.", "Post-procesando audio...")

    def yt_dlp_postprocessor_hook(self, d):
        if d['status'] == 'started':
            self.run_in_gui_thread(self.update_progress_ui, 100.0, "Conversión de formato iniciada...", "Codificando a MP3 de alta calidad (192kbps)...")
        elif d['status'] == 'finished' and d['postprocessor'] == 'ExtractAudio':
            self.run_in_gui_thread(self.update_progress_ui, 100.0, "Conversión finalizada con éxito.", "Preparando transferencia USB...")

    def update_progress_ui(self, percent, status_text, details_text):
        """Update progress bar values and status labels."""
        self.progress_bar.set_progress(percent)
        self.progress_lbl.config(text=status_text)
        self.progress_details.config(text=details_text)

    def cleanup_and_release_gui(self):
        """Restore GUI state back to active/enabled after process finishes."""
        self.ui_state = "ready"
        self.run_in_gui_thread(self.toggle_download_button)

    # DYNAMIC ENGINE AUTO-UPDATER
    def update_yt_dlp(self):
        """Updates yt-dlp library via pip in the background thread."""
        if self.ui_state == "busy":
            return
            
        # Comprobar si la aplicación está empaquetada como ejecutable (.exe con PyInstaller)
        is_frozen = getattr(sys, 'frozen', False)
        if is_frozen:
            messagebox.showinfo(
                "Función no disponible",
                "La actualización automática a través de pip no está disponible en la versión ejecutable (.exe).\n\n"
                "Para actualizar yt-dlp, descargue la versión ejecutable más reciente de la aplicación."
            )
            return
            
        confirm = messagebox.askyesno(
            "Actualizar yt-dlp",
            "¿Desea buscar y descargar actualizaciones para el motor de descarga (yt-dlp)?\n\n"
            "Es útil hacerlo si las descargas de YouTube fallan debido a cambios en la plataforma."
        )
        if not confirm:
            return
            
        self.ui_state = "busy"
        self.toggle_download_button()
        
        self.progress_lbl.config(text="Actualizando descargador...", fg=STYLE["fg"])
        self.progress_details.config(text="Ejecutando actualización de yt-dlp a través de pip...")
        self.progress_bar.set_progress(10)
        
        threading.Thread(target=self.update_yt_dlp_worker, daemon=True).start()

    def update_yt_dlp_worker(self):
        self.run_in_gui_thread(self.log_message, "\n--- INICIANDO ACTUALIZACIÓN DEL MOTOR DE DESCARGA ---\n")
        self.run_in_gui_thread(self.log_message, f"Ejecutando: {sys.executable} -m pip install --upgrade yt-dlp...\n")
        
        try:
            # Hide console window on Windows during execution
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            process = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                startupinfo=startupinfo
            )
            
            self.run_in_gui_thread(self.progress_bar.set_progress, 40)
            
            for line in process.stdout:
                self.run_in_gui_thread(self.log_message, line)
                
            process.wait()
            self.run_in_gui_thread(self.progress_bar.set_progress, 100)
            
            if process.returncode == 0:
                self.run_in_gui_thread(self.log_message, "--- MOTOR DE DESCARGA ACTUALIZADO CON ÉXITO ---\n\n")
                self.run_in_gui_thread(messagebox.showinfo, "Éxito", "yt-dlp se ha actualizado correctamente a la última versión disponible.")
                self.run_in_gui_thread(self.progress_lbl.config, text="Actualización completada")
                self.run_in_gui_thread(self.progress_details.config, text="El motor de descarga está listo.")
            else:
                self.run_in_gui_thread(self.log_message, f"--- ERROR DE ACTUALIZACIÓN: Código {process.returncode} ---\n\n", is_error=True)
                self.run_in_gui_thread(messagebox.showerror, "Error", f"La actualización falló con código de salida: {process.returncode}.")
                self.run_in_gui_thread(self.progress_lbl.config, text="Error en actualización")
                self.run_in_gui_thread(self.progress_details.config, text="No se pudo actualizar el motor.")
        except Exception as e:
            self.run_in_gui_thread(self.log_message, f"[ERROR] Excepción durante la actualización: {str(e)}\n\n", is_error=True)
            self.run_in_gui_thread(messagebox.showerror, "Error", f"Ocurrió un error al ejecutar pip: {str(e)}")
            self.run_in_gui_thread(self.progress_lbl.config, text="Error en actualización")
            self.run_in_gui_thread(self.progress_details.config, text=str(e))
            
        self.cleanup_and_release_gui()

if __name__ == "__main__":
    # Ensure Windows DPI scaling is handled so the fonts look sharp on high resolution screens
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware();
        except Exception:
            pass
            
    root = tk.Tk()
    app = YouTubeUSBApp(root)
    root.mainloop()
