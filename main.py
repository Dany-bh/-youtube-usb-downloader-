import os
import sys
import re
import json
import shutil
import ctypes
import string
import tempfile
import threading
import subprocess
import yt_dlp
import flet as ft

# Config helpers
def load_config():
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                return config.get("download_path", "")
    except Exception:
        pass
    return ""

def save_config(path):
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"download_path": path}, f, indent=4)
    except Exception:
        pass

# Windows API USB scanning helpers
def get_volume_label(drive_path):
    volumeNameBuffer = ctypes.create_unicode_buffer(1024)
    fileSystemNameBuffer = ctypes.create_unicode_buffer(1024)
    serial_number = ctypes.c_ulong(0)
    max_component_length = ctypes.c_ulong(0)
    file_system_flags = ctypes.c_ulong(0)
    
    try:
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
    except Exception:
        pass
    return ""

def get_usb_drives():
    drives = []
    if os.name != 'nt':
        return drives # USB detection via ctypes is Windows only
        
    try:
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drive_path = f"{letter}:\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
                if drive_type == 2: # DRIVE_REMOVABLE
                    try:
                        usage = shutil.disk_usage(drive_path)
                        free_gb = usage.free / (1024 ** 3)
                        total_gb = usage.total / (1024 ** 3)
                        label = get_volume_label(drive_path)
                        name = f"Unidad {letter} ({label})" if label else f"Unidad {letter}"
                        drives.append({
                            'path': drive_path,
                            'display': f"🔌 {name} - {free_gb:.2f} GB libres de {total_gb:.2f} GB",
                            'free_bytes': usage.free
                        })
                    except Exception:
                        drives.append({
                            'path': drive_path,
                            'display': f"🔌 Unidad {letter}:\\ (No disponible)",
                            'free_bytes': 0
                        })
            bitmask >>= 1
    except Exception:
        pass
    return drives

def get_default_mobile_download_path():
    android_download = "/storage/emulated/0/Download"
    if os.path.exists(android_download):
        return android_download
    try:
        user_downloads = os.path.expanduser("~/Downloads")
        if not os.path.exists(user_downloads):
            os.makedirs(user_downloads, exist_ok=True)
        return user_downloads
    except Exception:
        return tempfile.gettempdir()

def sanitize_filename(name):
    cleaned = re.sub(r'[\\/*?:"<>|]', '', name)
    cleaned = cleaned.strip().strip('.')
    if not cleaned:
        cleaned = "audio_youtube"
    return cleaned[:150]

def cleanup_temp_files(temp_dir, temp_file_base):
    try:
        for filename in os.listdir(temp_dir):
            if filename.startswith(temp_file_base):
                try:
                    os.remove(os.path.join(temp_dir, filename))
                except Exception:
                    pass
    except Exception:
        pass

class YouTubeUSBApp:
    def __init__(self, page: ft.Page):
        self.page = page
        self.page.title = "YouTube USB Downloader"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = "#0B0F19"
        
        # Responsive Page constraints
        self.page.window.width = 680
        self.page.window.height = 760
        self.page.window.min_width = 500
        self.page.window.min_height = 650
        self.page.padding = 20
        self.page.scroll = ft.ScrollMode.ADAPTIVE
        
        self.ui_state = "ready"
        self.selected_path = load_config()
        self.scanned_drives_data = []
        
        # Build interface
        self.create_widgets()
        self.refresh_destinations()
        
    def create_widgets(self):
        # 1. Title Header
        self.header = ft.Column(
            [
                ft.Row(
                    [
                        ft.Icon(name=ft.Icons.PLAY_CIRCLE_FILLED, color=ft.colors.BLUE_500, size=32),
                        ft.Text(
                            "YouTube USB Downloader",
                            size=26,
                            weight=ft.FontWeight.BOLD,
                            font_family="sans-serif",
                            color=ft.colors.WHITE
                        )
                    ],
                    alignment=ft.MainAxisAlignment.START
                ),
                ft.Text(
                    "Descarga y convierte videos directamente en tu móvil o PC.",
                    color=ft.colors.BLUE_GREY_400,
                    size=13,
                    italic=True
                )
            ],
            spacing=5
        )

        # 2. STEP 1: Paste Link
        self.url_input = ft.TextField(
            hint_text="Pega el enlace de YouTube aquí...",
            bgcolor="#0F172A",
            border_color="#475569",
            focused_border_color=ft.colors.BLUE_500,
            text_size=14,
            expand=True,
            on_change=self.on_url_change
        )
        
        self.btn_paste = ft.ElevatedButton(
            "Pegar",
            icon=ft.Icons.PASTE,
            color=ft.colors.WHITE,
            bgcolor=ft.colors.BLUE_600,
            on_click=self.paste_clipboard
        )
        
        # Metadata preview
        self.meta_card = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(name=ft.Icons.MUSIC_NOTE, color=ft.colors.EMERALD_400, size=24),
                    ft.Column(
                        [
                            ft.Text("Ingresa un enlace para ver los detalles...", size=13, color=ft.colors.BLUE_GREY_400, weight=ft.FontWeight.W_600, key="title"),
                            ft.Text("", size=11, color=ft.colors.BLUE_GREY_500, key="channel")
                        ],
                        spacing=2,
                        tight=True
                    )
                ]
            ),
            bgcolor="rgba(16, 185, 129, 0.05)",
            border=ft.border.all(1, "rgba(16, 185, 129, 0.2)"),
            border_radius=12,
            padding=12,
            visible=False
        )

        # 3. STEP 2: Destination Select
        self.destination_dropdown = ft.Dropdown(
            label="Destino de la descarga",
            bgcolor="#0F172A",
            border_color="#475569",
            focused_border_color=ft.colors.BLUE_500,
            text_size=14,
            expand=True,
            on_change=self.on_destination_change
        )
        
        self.btn_refresh = ft.IconButton(
            icon=ft.Icons.ROTATE_RIGHT_SHARP,
            icon_color=ft.colors.BLUE_GREY_400,
            bgcolor="#0F172A",
            on_click=self.on_refresh_click
        )
        
        self.btn_browse = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            icon_color=ft.colors.BLUE_GREY_400,
            bgcolor="#0F172A",
            visible=os.name == 'nt', # Only show folder picker on PC
            on_click=self.browse_pc_directory
        )

        # 4. STEP 3: Legal consent
        self.consent_checkbox = ft.Checkbox(
            label="Confirmo que tengo los derechos, licencias o la expresa autorización para descargar este audio.",
            value=False,
            label_style=ft.TextStyle(color=ft.colors.BLUE_GREY_400, size=12),
            on_change=self.validate_form
        )

        # 5. STEP 4: Live Progress Monitoring
        self.progress_status = ft.Text("Preparando descarga...", size=13, weight=ft.FontWeight.BOLD)
        self.progress_details = ft.Text("Conectando...", size=11, color=ft.colors.BLUE_GREY_400)
        self.progress_bar = ft.ProgressBar(value=0, color=ft.colors.EMERALD_500, bgcolor="#0F172A", height=8)
        
        self.console_box = ft.TextField(
            multiline=True,
            read_only=True,
            text_style=ft.TextStyle(font_family="monospace", size=10, color="#A3B3C9"),
            bgcolor="#05070C",
            border_color="#475569",
            height=120,
            expand=True
        )

        self.progress_panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row([self.progress_status], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    self.progress_details,
                    self.progress_bar,
                    ft.Text("Consola de logs:", size=11, color=ft.colors.BLUE_GREY_400),
                    self.console_box
                ],
                spacing=8
            ),
            bgcolor="rgba(15, 23, 42, 0.4)",
            border=ft.border.all(1, "#334155"),
            border_radius=16,
            padding=16,
            visible=False
        )

        # 6. Action Triggers
        self.btn_update = ft.ElevatedButton(
            "Actualizar Motor",
            icon=ft.Icons.CLOUD_DOWNLOAD,
            color=ft.colors.BLUE_GREY_200,
            bgcolor="#0F172A",
            on_click=self.update_yt_dlp,
            visible=os.name == 'nt' # update only available on python script PC
        )

        self.btn_download = ft.ElevatedButton(
            "Descargar y Guardar",
            icon=ft.Icons.DOWNLOAD_FOR_OFFLINE,
            color=ft.colors.WHITE,
            bgcolor=ft.colors.EMERALD_600,
            disabled=True,
            on_click=self.start_download
        )

        # Build Main View Layout
        self.page.add(
            ft.Container(
                content=ft.Column(
                    [
                        self.header,
                        ft.Divider(color="#334155", height=10),
                        
                        # Step 1 Section
                        ft.Column([
                            ft.Text("Paso 1: Pegar enlace de YouTube", size=14, color=ft.colors.BLUE_500, weight=ft.FontWeight.W_600),
                            ft.Row([self.url_input, self.btn_paste], spacing=10),
                            self.meta_card
                        ], spacing=6),
                        
                        # Step 2 Section
                        ft.Column([
                            ft.Text("Paso 2: Destino de la descarga", size=14, color=ft.colors.BLUE_500, weight=ft.FontWeight.W_600),
                            ft.Row([self.destination_dropdown, self.btn_refresh, self.btn_browse], spacing=10),
                        ], spacing=6),
                        
                        # Step 3 Section
                        ft.Column([
                            ft.Text("Paso 3: Autorización legal", size=14, color=ft.colors.BLUE_500, weight=ft.FontWeight.W_600),
                            self.consent_checkbox,
                        ], spacing=6),
                        
                        # Step 4 Section
                        self.progress_panel,
                        
                        # Footer Buttons
                        ft.Row(
                            [
                                self.btn_update,
                                self.btn_download
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                        )
                    ],
                    spacing=22,
                    expand=True
                ),
                padding=20,
                bgcolor="rgba(30, 41, 59, 0.7)",
                border=ft.border.all(1, "rgba(71, 85, 105, 0.4)"),
                border_radius=24,
                shadow=ft.BoxShadow(blur_radius=30, color="rgba(0,0,0,0.4)")
            )
        )

    def log_message(self, text, is_error=False):
        current_logs = self.console_box.value or ""
        # Limitar logs a últimas 400 líneas
        log_lines = current_logs.splitlines()
        if len(log_lines) > 400:
            log_lines = log_lines[-400:]
        log_lines.append(text)
        self.console_box.value = "\n".join(log_lines)
        self.page.update()

    def update_progress_ui(self, percent, status, details):
        self.progress_bar.value = percent / 100.0
        self.progress_status.value = status
        self.progress_details.value = details
        self.page.update()

    def paste_clipboard(self, e):
        # Read clip text directly from Flet page API
        clip_text = self.page.get_clipboard()
        if clip_text:
            self.url_input.value = clip_text
            self.on_url_change(None)
        else:
            self.page.show_snack_bar(ft.SnackBar(ft.Text("Portapapeles vacío o inaccesible.")))

    def on_url_change(self, e):
        url = self.url_input.value.strip()
        if not url:
            self.meta_card.visible = False
            self.validate_form(None)
            self.page.update()
            return
            
        if "youtube.com/" in url or "youtu.be/" in url:
            self.meta_card.visible = True
            self.meta_card.content.controls[1].controls[0].value = "🔍 Consultando detalles del video..."
            self.meta_card.content.controls[1].controls[0].color = ft.colors.BLUE_400
            self.meta_card.content.controls[1].controls[1].value = "Por favor, espera..."
            self.page.update()
            
            # Run async fetch in background thread
            threading.Thread(target=self.fetch_metadata_worker, args=(url,), daemon=True).start()
        else:
            self.meta_card.visible = True
            self.meta_card.content.controls[1].controls[0].value = "⚠️ URL no válida."
            self.meta_card.content.controls[1].controls[0].color = ft.colors.RED_400
            self.meta_card.content.controls[1].controls[1].value = "Por favor, introduce un enlace de YouTube válido."
            self.page.update()
        self.validate_form(None)

    def fetch_metadata_worker(self, url):
        try:
            ydl_opts = {
                'extract_flat': True,
                'skip_download': True,
                'noplaylist': True,
                'check_formats': False
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if self.url_input.value.strip() != url:
                    return
                title = info.get('title', 'Título desconocido')
                uploader = info.get('uploader', 'Canal desconocido')
                duration_secs = info.get('duration')
                
                duration_str = ""
                if duration_secs:
                    mins, secs = divmod(int(duration_secs), 60)
                    duration_str = f" | Duración: {mins}m {secs}s"
                
                self.meta_card.content.controls[1].controls[0].value = title
                self.meta_card.content.controls[1].controls[0].color = ft.colors.WHITE
                self.meta_card.content.controls[1].controls[1].value = f"Canal: {uploader}{duration_str}"
                self.page.update()
        except Exception:
            if self.url_input.value.strip() == url:
                self.meta_card.content.controls[1].controls[0].value = "⚠️ Error de extracción."
                self.meta_card.content.controls[1].controls[0].color = ft.colors.BLUE_GREY_400
                self.meta_card.content.controls[1].controls[1].value = "No se pudieron obtener los detalles."
                self.page.update()

    def on_destination_change(self, e):
        path = self.destination_dropdown.value
        if path:
            self.selected_path = path
            save_config(self.selected_path)
        self.validate_form(None)

    def on_refresh_click(self, e):
        self.refresh_destinations()

    def refresh_destinations(self):
        options = []
        drives = get_usb_drives()
        self.scanned_drives_data = drives
        
        # Add Mobile storage option first if not Windows
        if os.name != 'nt':
            mobile_path = get_default_mobile_download_path()
            try:
                usage = shutil.disk_usage(mobile_path)
                free_gb = usage.free / (1024 ** 3)
                display = f"📲 Almacenamiento Móvil - {free_gb:.2f} GB libres"
                options.append(ft.dropdown.Option(key=mobile_path, text=display))
                self.scanned_drives_data.append({'path': mobile_path, 'free_bytes': usage.free})
            except Exception:
                options.append(ft.dropdown.Option(key=mobile_path, text="📲 Almacenamiento Móvil"))
                self.scanned_drives_data.append({'path': mobile_path, 'free_bytes': 0})
        
        # Add Scanned USB drives
        for d in drives:
            options.append(ft.dropdown.Option(key=d['path'], text=d['display']))
            
        # Add custom PC folder if saved and not already added
        saved_path = load_config()
        if saved_path and os.path.exists(saved_path):
            norm_saved = os.path.abspath(saved_path).lower().rstrip(os.sep)
            already_added = False
            for d in self.scanned_drives_data:
                if os.path.abspath(d['path']).lower().rstrip(os.sep) == norm_saved:
                    already_added = True
                    break
            if not already_added:
                try:
                    usage = shutil.disk_usage(saved_path)
                    free_gb = usage.free / (1024 ** 3)
                    display = f"📁 Carpeta PC: {saved_path} - {free_gb:.2f} GB libres"
                    options.append(ft.dropdown.Option(key=saved_path, text=display))
                    self.scanned_drives_data.append({'path': saved_path, 'free_bytes': usage.free})
                except Exception:
                    options.append(ft.dropdown.Option(key=saved_path, text=f"📁 Carpeta PC: {saved_path} (No disponible)"))
                    self.scanned_drives_data.append({'path': saved_path, 'free_bytes': 0})

        self.destination_dropdown.options = options
        
        # Restore selection
        if self.selected_path:
            norm_selected = os.path.abspath(self.selected_path).lower().rstrip(os.sep)
            found = False
            for d in self.scanned_drives_data:
                if os.path.abspath(d['path']).lower().rstrip(os.sep) == norm_selected:
                    self.destination_dropdown.value = d['path']
                    found = True
                    break
            if not found and options:
                self.destination_dropdown.value = options[0].key
                self.selected_path = options[0].key
        elif options:
            self.destination_dropdown.value = options[0].key
            self.selected_path = options[0].key
            
        self.page.update()

    def browse_pc_directory(self, e):
        # Flet handles native folder picker securely in local environments
        # We can implement using the Flet FilePicker component if needed, 
        # but in local scripts, standard python is fine. Let's do Flet FilePicker:
        def on_picker_result(res: ft.FilePickerResultEvent):
            if res.path:
                path = os.path.abspath(res.path)
                self.selected_path = path
                save_config(self.selected_path)
                self.refresh_destinations()
                
        picker = ft.FilePicker(on_result=on_picker_result)
        self.page.overlay.append(picker)
        self.page.update()
        picker.get_directory_path(dialog_title="Seleccionar Carpeta de Destino")

    def validate_form(self, e):
        url = self.url_input.value.strip()
        is_url_ok = "youtube.com/" in url or "youtu.be/" in url
        is_consent_ok = self.consent_checkbox.value
        has_destination = self.destination_dropdown.value is not None
        
        if is_url_ok and is_consent_ok and has_destination and self.ui_state == "ready":
            self.btn_download.disabled = False
        else:
            self.btn_download.disabled = True
        self.page.update()

    def set_ui_state(self, state):
        self.ui_state = state
        if state == "busy":
            self.url_input.disabled = True
            self.btn_paste.disabled = True
            self.destination_dropdown.disabled = True
            self.btn_refresh.disabled = True
            self.btn_browse.disabled = True
            self.consent_checkbox.disabled = True
            self.btn_update.disabled = True
            self.btn_download.disabled = True
        else:
            self.url_input.disabled = False
            self.btn_paste.disabled = False
            self.destination_dropdown.disabled = False
            self.btn_refresh.disabled = False
            self.btn_browse.disabled = False
            self.consent_checkbox.disabled = False
            self.btn_update.disabled = False
            self.validate_form(None)
        self.page.update()

    def start_download(self, e):
        url = self.url_input.value.strip()
        dest = self.destination_dropdown.value
        
        if not url or not dest:
            return
            
        selected_drive = None
        for d in self.scanned_drives_data:
            if d['path'] == dest:
                selected_drive = d
                break
                
        if not selected_drive or selected_drive['free_bytes'] == 0:
            self.show_popup("Destino inválido", "El almacenamiento de destino no está accesible actualmente.", "error")
            return
            
        self.set_ui_state("busy")
        self.progress_panel.visible = True
        self.console_box.value = ""
        self.update_progress_ui(0, "Preparando descarga...", "Iniciando subproceso de descarga...")
        
        threading.Thread(target=self.download_worker, args=(url, selected_drive), daemon=True).start()

    def download_worker(self, url, drive_info):
        dest_path_dir = drive_info['path']
        temp_dir = tempfile.gettempdir()
        video_id = ""
        title = "audio_youtube"
        
        self.log_message(f"[INICIO] Iniciando descarga: {url}\n")
        self.log_message(f"[DESTINO] Guardando en: {dest_path_dir}\n")
        
        # 1. Fetch metadata
        try:
            self.update_progress_ui(0, "Conectando con YouTube...", "Extrayendo metadatos...")
            ydl_opts_meta = {'noplaylist': True, 'check_formats': False}
            with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
                info = ydl.extract_info(url, download=False)
                video_id = info.get('id', 'temp_id')
                title = info.get('title', 'audio_youtube')
                self.log_message(f"[VIDEO] Título: {title}\n")
        except Exception as e:
            error_line = str(e).splitlines()[0]
            self.log_message(f"[ERROR] Metadatos fallidos: {error_line}\n", is_error=True)
            self.show_popup("Error de Conexión", f"No se pudo conectar a YouTube.\nDetalle: {error_line}", "error")
            self.set_ui_state("ready")
            return

        # Check for FFmpeg dynamically
        has_ffmpeg = shutil.which('ffmpeg') is not None
        ext = "mp3" if has_ffmpeg else "m4a"
        temp_file_base = f"yt_audio_{video_id}"
        local_file_path = os.path.join(temp_dir, f"{temp_file_base}.{ext}")
        
        # Cleanup
        self.log_message("[SISTEMA] Limpiando archivos temporales...\n")
        cleanup_temp_files(temp_dir, temp_file_base)

        # Options
        ydl_opts = {
            'noplaylist': True,
            'outtmpl': os.path.join(temp_dir, f"{temp_file_base}.%(ext)s"),
            'progress_hooks': [self.yt_dlp_progress_hook],
            'logger': YTDLPLogger(self),
            'restrictfilenames': True,
            'concurrent_fragment_downloads': 8,
            'check_formats': False,
        }
        
        if has_ffmpeg:
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        else:
            self.log_message("[INFO] FFmpeg no disponible. Descargando audio nativo m4a.\n")
            ydl_opts['format'] = 'm4a/bestaudio'

        # 2. Download
        try:
            self.update_progress_ui(10, "Descargando flujo...", "Obteniendo datos de audio...")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        except Exception as e:
            error_line = str(e).splitlines()[0]
            self.log_message(f"[ERROR] Fallo al descargar: {error_line}\n", is_error=True)
            self.show_popup("Error en descarga", f"No se pudo completar la descarga.\nDetalle: {error_line}", "error")
            cleanup_temp_files(temp_dir, temp_file_base)
            self.set_ui_state("ready")
            return

        # Confirm file
        if not os.path.exists(local_file_path):
            self.log_message(f"[ERROR] Archivo .{ext} no disponible.\n", is_error=True)
            self.show_popup("Error de archivo", f"No se encontró el archivo temporal .{ext}.", "error")
            self.set_ui_state("ready")
            return

        file_size_bytes = os.path.getsize(local_file_path)
        file_size_mb = file_size_bytes / (1024 * 1024)
        self.log_message(f"[SISTEMA] Archivo generado ({file_size_mb:.2f} MB).\n")

        # 3. Copy to Destination
        try:
            usage = shutil.disk_usage(dest_path_dir)
            if usage.free < file_size_bytes:
                raise ValueError("Espacio en disco insuficiente en destino.")
        except Exception as e:
            self.log_message(f"[ERROR] Espacio insuficiente: {str(e)}\n", is_error=True)
            self.show_popup("Espacio Insuficiente", f"No hay espacio suficiente en el almacenamiento.\nNecesario: {file_size_mb:.2f} MB", "error")
            cleanup_temp_files(temp_dir, temp_file_base)
            self.set_ui_state("ready")
            return

        sanitized_title = sanitize_filename(title)
        dest_filename = f"{sanitized_title}.{ext}"
        dest_path = os.path.join(dest_path_dir, dest_filename)
        
        # Prevent collisions
        counter = 1
        while os.path.exists(dest_path):
            dest_filename = f"{sanitized_title} ({counter}).{ext}"
            dest_path = os.path.join(dest_path_dir, dest_filename)
            counter += 1

        try:
            self.log_message(f"[SISTEMA] Escribiendo archivo en destino: {dest_path}\n")
            self.copy_file_local_with_progress(local_file_path, dest_path)
            self.log_message(f"[SISTEMA] Completado!\n")
            self.update_progress_ui(100, "Completado con éxito", f"Guardado como: {dest_filename}")
            self.show_popup("¡Descarga Completada!", f"El archivo se ha guardado correctamente como:\n{dest_filename}", "success")
        except Exception as e:
            self.log_message(f"[ERROR] Error al copiar: {str(e)}\n", is_error=True)
            self.show_popup("Error de guardado", f"No se pudo copiar el archivo al destino.\nDetalle: {str(e)}", "error")
        finally:
            cleanup_temp_files(temp_dir, temp_file_base)

        self.refresh_destinations()
        self.set_ui_state("ready")

    def copy_file_local_with_progress(self, src, dst):
        total_size = os.path.getsize(src)
        copied_bytes = 0
        buffer_size = 512 * 1024
        
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
                    
                    self.update_progress_ui(
                        percent, 
                        f"Guardando archivo: {percent:.1f}%", 
                        f"Escribiendo {copied_mb:.1f} MB de {total_mb:.1f} MB..."
                    )
                fdst.flush()
                try:
                    os.fsync(fdst.fileno())
                except Exception:
                    pass

    def yt_dlp_progress_hook(self, d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            speed = d.get('speed', 0)
            eta = d.get('eta', 0)
            
            percent = (downloaded / total * 100.0) if total > 0 else 0.0
            speed_str = f"{speed / (1024*1024):.2f} MB/s" if speed and speed > 1024*1024 else (f"{speed/1024:.2f} KB/s" if speed else "Calculando...")
            eta_str = f"{eta//60}m {eta%60}s" if eta else "--"
            
            dl_mb = downloaded / (1024 * 1024)
            tot_mb = total / (1024 * 1024)
            
            self.update_progress_ui(
                percent, 
                f"Descargando audio: {percent:.1f}%", 
                f"{dl_mb:.1f} MB de {tot_mb:.1f} MB | Vel: {speed_str} | ETA: {eta_str}"
            )

    def update_yt_dlp(self, e):
        self.set_ui_state("busy")
        self.progress_panel.visible = True
        self.console_box.value = ""
        self.update_progress_ui(20, "Actualizando engine...", "Llamando a pip...")
        threading.Thread(target=self.update_yt_dlp_worker, daemon=True).start()

    def update_yt_dlp_worker(self):
        self.log_message("--- INICIANDO ACTUALIZACIÓN DEL MOTOR DE DESCARGA ---\n")
        self.log_message(f"Ejecutando: {sys.executable} -m pip install --upgrade yt-dlp...\n")
        
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            process = subprocess.Popen(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                startupinfo=startupinfo
            )
            
            for line in process.stdout:
                self.log_message(line)
                
            process.wait()
            self.update_progress_ui(100, "Actualización completada", "yt-dlp está listo.")
            
            if process.returncode == 0:
                self.show_popup("Actualización Exitosa", "El motor de descarga se ha actualizado correctamente.", "success")
            else:
                self.show_popup("Error de Actualización", "pip devolvió código de error.", "error")
        except Exception as e:
            self.show_popup("Error al actualizar", str(e), "error")
            
        self.set_ui_state("ready")

    def show_popup(self, title, message, type="info"):
        # Flet Alert Dialog with custom animations
        icon_name = ft.Icons.CHECK_CIRCLE if type == "success" else (ft.Icons.ERROR_OUTLINE if type == "error" else ft.Icons.INFO_OUTLINE)
        icon_color = ft.colors.EMERALD_400 if type == "success" else (ft.colors.RED_400 if type == "error" else ft.colors.BLUE_400)
        
        def close_dialog(e):
            dialog.open = False
            self.page.update()
            
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row([ft.Icon(icon_name, color=icon_color, size=30), ft.Text(title, weight=ft.FontWeight.BOLD)], spacing=10),
            content=ft.Text(message, size=14, color=ft.colors.BLUE_GREY_200),
            actions=[
                ft.TextButton("Entendido", on_click=close_dialog, style=ft.ButtonStyle(color=icon_color))
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.overlay.append(dialog)
        self.page.update()
        dialog.open = True
        self.page.update()

# Logging bridge
class YTDLPLogger:
    def __init__(self, app):
        self.app = app
    def debug(self, msg):
        if msg.strip(): self.app.log_message(f"[INFO] {msg}\n")
    def info(self, msg):
        if msg.strip(): self.app.log_message(f"[INFO] {msg}\n")
    def warning(self, msg):
        if msg.strip(): self.app.log_message(f"[WARN] {msg}\n", is_error=True)
    def error(self, msg):
        if msg.strip(): self.app.log_message(f"[ERROR] {msg}\n", is_error=True)

def main(page: ft.Page):
    YouTubeUSBApp(page)

if __name__ == '__main__':
    ft.app(target=main)
