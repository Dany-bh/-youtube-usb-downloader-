import os
import sys
import re
import json
import queue
import shutil
import ctypes
import string
import socket
import tempfile
import threading
import subprocess
import yt_dlp
from flask import Flask, render_template, jsonify, request, Response, send_from_directory

app = Flask(__name__)
server_state = "ready"
event_queue = queue.Queue()

# Load/Save config helpers
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

def get_all_destinations():
    drives = get_usb_drives()
    saved_path = load_config()
    if saved_path:
        norm_selected = os.path.abspath(saved_path).lower().rstrip(os.sep)
        already_exists = False
        for d in drives:
            norm_d = os.path.abspath(d['path']).lower().rstrip(os.sep)
            if norm_d == norm_selected:
                already_exists = True
                break
        if not already_exists:
            try:
                usage = shutil.disk_usage(saved_path)
                free_gb = usage.free / (1024 ** 3)
                total_gb = usage.total / (1024 ** 3)
                display = f"📁 Carpeta PC: {saved_path} - {free_gb:.2f} GB libres de {total_gb:.2f} GB"
                drives.append({
                    'path': saved_path,
                    'display': display,
                    'free_bytes': usage.free
                })
            except Exception:
                drives.append({
                    'path': saved_path,
                    'display': f"📁 Carpeta PC: {saved_path} (No disponible)",
                    'free_bytes': 0
                })
    return drives

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

# Network / SSE Logging & Progress
class WebYTDLPLogger:
    def debug(self, msg):
        if msg.strip():
            event_queue.put({"type": "log", "text": f"[INFO] {msg}\n"})
    def info(self, msg):
        if msg.strip():
            event_queue.put({"type": "log", "text": f"[INFO] {msg}\n"})
    def warning(self, msg):
        if msg.strip():
            event_queue.put({"type": "log", "text": f"[WARN] {msg}\n", "is_error": True})
    def error(self, msg):
        if msg.strip():
            event_queue.put({"type": "log", "text": f"[ERROR] {msg}\n", "is_error": True})

def web_yt_dlp_progress_hook(d):
    if d['status'] == 'downloading':
        downloaded = d.get('downloaded_bytes', 0)
        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
        speed = d.get('speed', 0)
        eta = d.get('eta', 0)
        
        percent = (downloaded / total * 100.0) if total > 0 else 0.0
        
        if speed:
            if speed > 1024 * 1024:
                speed_str = f"{speed / (1024 * 1024):.2f} MB/s"
            else:
                speed_str = f"{speed / 1024:.2f} KB/s"
        else:
            speed_str = "Calculando..."
            
        if eta:
            mins, secs = divmod(int(eta), 60)
            eta_str = f"{mins}m {secs}s"
        else:
            eta_str = "--"
            
        dl_mb = downloaded / (1024 * 1024)
        tot_mb = total / (1024 * 1024)
        
        status_text = f"Descargando audio: {percent:.1f}%"
        details_text = f"{dl_mb:.1f} MB de {tot_mb:.1f} MB | Vel: {speed_str} | ETA: {eta_str}"
        
        event_queue.put({
            "type": "progress",
            "percent": percent,
            "status": status_text,
            "details": details_text
        })
    elif d['status'] == 'finished':
        event_queue.put({
            "type": "progress",
            "percent": 100.0,
            "status": "Descarga de flujo completada.",
            "details": "Post-procesando audio..."
        })

def web_yt_dlp_postprocessor_hook(d):
    if d['status'] == 'started':
        event_queue.put({
            "type": "progress",
            "percent": 100.0,
            "status": "Conversión de formato iniciada...",
            "details": "Codificando a MP3 de alta calidad (192kbps)..."
        })
    elif d['status'] == 'finished' and d['postprocessor'] == 'ExtractAudio':
        event_queue.put({
            "type": "progress",
            "percent": 100.0,
            "status": "Conversión finalizada con éxito.",
            "details": "Preparando transferencia..."
        })

def copy_file_local_with_progress(src, dst):
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
                
                status_text = f"Copiando archivo: {percent:.1f}%"
                details_text = f"Escribiendo {copied_mb:.1f} MB de {total_mb:.1f} MB..."
                
                event_queue.put({
                    "type": "progress",
                    "percent": percent,
                    "status": status_text,
                    "details": details_text
                })
            
            event_queue.put({
                "type": "progress",
                "percent": 99.0,
                "status": "Finalizando transferencia...",
                "details": "Vaciando búfer físico..."
            })
            fdst.flush()
            try:
                os.fsync(fdst.fileno())
            except Exception:
                pass

# Background threads
def download_thread_worker(url, destination):
    global server_state
    server_state = "busy"
    
    temp_dir = tempfile.gettempdir()
    video_id = ""
    title = "audio_youtube"
    
    event_queue.put({"type": "log", "text": f"\n[INICIO] Iniciando descarga para enlace: {url}\n"})
    event_queue.put({"type": "log", "text": f"[SISTEMA] Destino seleccionado: {destination}\n"})
    
    # 1. Fetch Title and ID
    try:
        event_queue.put({"type": "progress", "percent": 0, "status": "Conectando con YouTube...", "details": "Extrayendo información..."})
        ydl_opts_meta = {'noplaylist': True, 'check_formats': False}
        with yt_dlp.YoutubeDL(ydl_opts_meta) as ydl:
            info = ydl.extract_info(url, download=False)
            video_id = info.get('id', 'temp_id')
            title = info.get('title', 'audio_youtube')
            event_queue.put({"type": "log", "text": f"[VIDEO] Título: {title}\n"})
    except Exception as e:
        error_line = str(e).splitlines()[0]
        event_queue.put({"type": "log", "text": f"[ERROR] Extracción de metadatos fallida: {error_line}\n", "is_error": True})
        event_queue.put({"type": "error", "message": f"No se pudo conectar a YouTube.\n\nDetalle: {error_line}"})
        server_state = "ready"
        return

    # Check if FFmpeg is available on the hosting system
    has_ffmpeg = shutil.which('ffmpeg') is not None
    ext = "mp3" if has_ffmpeg else "m4a"
    
    # Prepare filenames
    temp_file_base = f"yt_audio_{video_id}"
    local_file_path = os.path.join(temp_dir, f"{temp_file_base}.{ext}")
    
    # Remove lingering files
    cleanup_temp_files(temp_dir, temp_file_base)

    # Options for extraction
    ydl_opts = {
        'noplaylist': True,
        'outtmpl': os.path.join(temp_dir, f"{temp_file_base}.%(ext)s"),
        'progress_hooks': [web_yt_dlp_progress_hook],
        'postprocessor_hooks': [web_yt_dlp_postprocessor_hook],
        'logger': WebYTDLPLogger(),
        'restrictfilenames': True,
        'concurrent_fragment_downloads': 8,
        'check_formats': False,
    }
    
    # Apply audio extraction post-processing if FFmpeg exists, else download raw AAC/m4a
    if has_ffmpeg:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        event_queue.put({"type": "log", "text": "[INFO] FFmpeg no detectado en el sistema. Se descargará audio AAC nativo (.m4a) sin conversión.\n"})
        ydl_opts['format'] = 'm4a/bestaudio'

    # 2. Start Download
    try:
        event_queue.put({"type": "log", "text": "[DESCARGA] Descargando flujo de audio desde YouTube...\n"})
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        error_line = str(e).splitlines()[0]
        event_queue.put({"type": "log", "text": f"[ERROR] Descarga/Conversión fallida: {error_line}\n", "is_error": True})
        event_queue.put({"type": "error", "message": f"El motor de descarga falló.\n\nDetalle: {error_line}"})
        cleanup_temp_files(temp_dir, temp_file_base)
        server_state = "ready"
        return

    # Confirm download exists
    if not os.path.exists(local_file_path):
        event_queue.put({"type": "log", "text": f"[ERROR] Archivo de audio .{ext} no disponible en temporales.\n", "is_error": True})
        event_queue.put({"type": "error", "message": f"No se pudo generar el archivo de audio .{ext}."})
        server_state = "ready"
        return

    file_size_bytes = os.path.getsize(local_file_path)
    file_size_mb = file_size_bytes / (1024 * 1024)
    event_queue.put({"type": "log", "text": f"[SISTEMA] Archivo de audio generado ({file_size_mb:.2f} MB).\n"})

    # 3. Save File
    if destination == "browser":
        # Keep the temp file so mobile device can retrieve it
        event_queue.put({
            "type": "complete",
            "download_url": f"/api/retrieve/{temp_file_base}.{ext}"
        })
    else:
        # Save to local folder/USB
        try:
            usage = shutil.disk_usage(destination)
            if usage.free < file_size_bytes:
                raise ValueError("Espacio libre insuficiente en la ruta de destino.")
        except Exception as e:
            event_queue.put({"type": "log", "text": f"[ERROR] Validación de espacio fallida: {str(e)}\n", "is_error": True})
            event_queue.put({"type": "error", "message": f"No hay espacio suficiente en la unidad seleccionada.\nNecesario: {file_size_mb:.2f} MB"})
            cleanup_temp_files(temp_dir, temp_file_base)
            server_state = "ready"
            return

        sanitized_title = sanitize_filename(title)
        dest_filename = f"{sanitized_title}.{ext}"
        dest_path = os.path.join(destination, dest_filename)
        
        # Collision prevention
        counter = 1
        while os.path.exists(dest_path):
            dest_filename = f"{sanitized_title} ({counter}).{ext}"
            dest_path = os.path.join(destination, dest_filename)
            counter += 1

        try:
            event_queue.put({"type": "log", "text": f"[SISTEMA] Copiando audio al destino local...\n"})
            copy_file_local_with_progress(local_file_path, dest_path)
            event_queue.put({"type": "log", "text": f"[SISTEMA] Archivo guardado correctamente en: {dest_path}\n"})
            event_queue.put({"type": "complete"})
        except Exception as e:
            event_queue.put({"type": "log", "text": f"[ERROR] Escritura fallida: {str(e)}\n", "is_error": True})
            event_queue.put({"type": "error", "message": f"No se pudo copiar el archivo.\n\nDetalle: {str(e)}"})
        finally:
            cleanup_temp_files(temp_dir, temp_file_base)

    server_state = "ready"

def update_yt_dlp_worker():
    global server_state
    server_state = "busy"
    event_queue.put({"type": "log", "text": "\n--- INICIANDO ACTUALIZACIÓN DEL MOTOR DE DESCARGA (PC) ---\n"})
    event_queue.put({"type": "log", "text": f"Ejecutando: {sys.executable} -m pip install --upgrade yt-dlp...\n"})
    
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
        
        event_queue.put({"type": "progress", "percent": 40, "status": "Actualizando...", "details": "Descargando e instalando yt-dlp..."})
        
        for line in process.stdout:
            event_queue.put({"type": "log", "text": line})
            
        process.wait()
        event_queue.put({"type": "progress", "percent": 100, "status": "Actualización completada", "details": "El motor de descarga está listo."})
        
        if process.returncode == 0:
            event_queue.put({"type": "log", "text": "--- MOTOR DE DESCARGA ACTUALIZADO CON ÉXITO ---\n\n"})
            event_queue.put({"type": "complete"})
        else:
            event_queue.put({"type": "log", "text": f"--- ERROR DE ACTUALIZACIÓN: Código {process.returncode} ---\n\n", "is_error": True})
            event_queue.put({"type": "error", "message": f"La actualización en el servidor falló (código {process.returncode})."})
    except Exception as e:
        event_queue.put({"type": "log", "text": f"[ERROR] Excepción de actualización: {str(e)}\n\n", "is_error": True})
        event_queue.put({"type": "error", "message": f"Error al ejecutar pip: {str(e)}"})
        
    server_state = "ready"

# Web application routing
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('static', 'sw.js')

@app.route('/api/status')
def get_status():
    has_ffmpeg = shutil.which('ffmpeg') is not None
    drives = get_all_destinations()
    return jsonify({
        "status": server_state,
        "has_ffmpeg": has_ffmpeg,
        "drives": drives
    })

@app.route('/api/drives')
def api_drives():
    return jsonify(get_all_destinations())

@app.route('/api/browse', methods=['POST'])
def api_browse():
    # Opens directory browser physically on the host PC screen
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(parent=root, title="Seleccionar Carpeta de Destino")
        root.destroy()
        if path:
            path = os.path.abspath(path)
            save_config(path)
            return jsonify({"status": "success", "path": path})
    except Exception as e:
        pass
    return jsonify({"status": "failed"})

@app.route('/api/metadata', methods=['POST'])
def api_metadata():
    url = request.json.get('url', '')
    if not url:
        return jsonify({"status": "error"})
        
    try:
        ydl_opts = {
            'extract_flat': True,
            'skip_download': True,
            'noplaylist': True,
            'check_formats': False
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            duration_secs = info.get('duration')
            duration_str = ""
            if duration_secs:
                mins, secs = divmod(int(duration_secs), 60)
                duration_str = f"{mins}m {secs}s"
                
            return jsonify({
                "status": "success",
                "title": info.get('title', 'Título desconocido'),
                "uploader": info.get('uploader', 'Canal desconocido'),
                "duration": duration_str
            })
    except Exception:
        pass
    return jsonify({"status": "failed"})

@app.route('/api/download', methods=['POST'])
def api_download():
    global server_state
    if server_state == "busy":
        return jsonify({"status": "error", "message": "El servidor está procesando otra descarga."})
        
    url = request.json.get('url', '')
    destination = request.json.get('destination', 'browser')
    
    if not url:
        return jsonify({"status": "error", "message": "Falta URL."})
        
    threading.Thread(target=download_thread_worker, args=(url, destination), daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/api/update', methods=['POST'])
def api_update():
    global server_state
    if server_state == "busy":
        return jsonify({"status": "error", "message": "El servidor está ocupado."})
        
    if getattr(sys, 'frozen', False):
        return jsonify({"status": "error", "message": "Actualización no disponible en modo ejecutable (.exe)."})
        
    threading.Thread(target=update_yt_dlp_worker, daemon=True).start()
    return jsonify({"status": "started"})

@app.route('/api/stream')
def api_stream():
    def event_generator():
        # Clear the queue first
        while not event_queue.empty():
            try: event_queue.get_nowait()
            except queue.Empty: break
            
        while True:
            try:
                ev = event_queue.get(timeout=20)
                yield f"data: {json.dumps(ev)}\n\n"
            except queue.Empty:
                yield "data: {\"type\": \"heartbeat\"}\n\n"
                
    return Response(event_generator(), mimetype='text/event-stream')

@app.route('/api/retrieve/<filename>')
def api_retrieve(filename):
    # Prevent directory traversal
    filename = os.path.basename(filename)
    if not re.match(r'^yt_audio_[a-zA-Z0-9_-]+\.(mp3|m4a)$', filename):
        return "Archivo inválido", 400
        
    temp_dir = tempfile.gettempdir()
    file_path = os.path.join(temp_dir, filename)
    if not os.path.exists(file_path):
        return "Archivo no encontrado", 404
        
    ext = filename.split('.')[-1]
    title = request.args.get('title', 'audio')
    safe_title = sanitize_filename(title) + f".{ext}"
    
    return send_from_directory(temp_dir, filename, as_attachment=True, download_name=safe_title)

# Get primary local IP address to print for mobile access
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == '__main__':
    local_ip = get_local_ip()
    port = 5000
    
    print("\n" + "="*70)
    print("YouTube USB Downloader - Servidor Web Iniciado con Exito")
    print(f"Acceso en tu PC:      http://localhost:{port}")
    print(f"Acceso en tu Celular: http://{local_ip}:{port}")
    print("Importante: El celular debe estar conectado a la misma red Wi-Fi.")
    print("="*70 + "\n")
    
    # Listen on all interfaces so mobile devices can access it via Wi-Fi IP
    app.run(host='0.0.0.0', port=port, debug=False)
