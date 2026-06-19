# YouTube USB Audio Downloader (Descargador de Audio a USB)

Esta es una aplicación de escritorio desarrollada en Python que permite extraer el audio de videos de YouTube, convertirlo a formato MP3 de alta calidad (192 kbps) y copiarlo directamente a cualquier memoria USB detectada en el sistema.

> [!IMPORTANT]
> Esta aplicación está diseñada **únicamente** para descargar videos sobre los cuales poseas los derechos de autor, licencias correspondientes o la autorización explícita del creador. Su uso para descargar material protegido por derechos de autor sin autorización está estrictamente prohibido.

---

## Características principales

1. **Diseño Moderno y Premium (Modo Oscuro):** Interfaz gráfica construida en Tkinter con un diseño adaptado (Paleta Slate de Tailwind, bordes planos y sin efectos obsoletos en 3D).
2. **Alta Definición Visual (DPI Aware):** Configurada para escalar y verse nítida en pantallas con resoluciones altas (High DPI en Windows).
3. **Detección Automática de Memorias USB (Hotplug):** La aplicación escanea continuamente tus puertos y detecta memorias USB de forma automática cada 5 segundos, mostrando la etiqueta de volumen y el espacio libre disponible.
4. **Validación de Espacio en Disco:** Antes de iniciar la transferencia de datos, calcula si la memoria USB tiene suficiente espacio libre para almacenar el archivo final.
5. **Prevención de Sobrescritura:** Si ya existe un archivo con el mismo nombre en la memoria USB, añade automáticamente un sufijo numérico (ej. `nombre (1).mp3`) en lugar de sobreescribirlo.
6. **Progreso Detallado e Hilos Separados:** Las tareas de descarga, conversión de audio a MP3 y copia al USB se ejecutan en hilos secundarios para que la interfaz nunca se congele. Además, muestra estadísticas detalladas como la velocidad de descarga y el tiempo estimado (ETA).
7. **Consola en Vivo:** Visualización directa de las operaciones de `yt-dlp` y `ffmpeg` para facilitar la depuración y dar transparencia al usuario.
8. **Actualizador del Motor Integrado:** Un botón dedicado que actualiza la librería `yt-dlp` a su última versión utilizando el mismo entorno de Python de la aplicación, solucionando posibles fallas si YouTube realiza cambios en su plataforma.

---

## Requisitos del Sistema

* **Sistema Operativo:** Windows (probado en Windows 10/11).
* **Python:** Versión 3.8 o superior (probado con Python 3.12.1).
* **FFmpeg:** Requerido para la conversión de audio a MP3.

---

## Instrucciones de Instalación

### Paso 1: Instalar dependencias de Python
Abre una terminal (PowerShell o CMD) en la carpeta del proyecto y ejecuta el siguiente comando:
```powershell
pip install -r requirements.txt
```
Esto instalará `yt-dlp` (la biblioteca encargada de descargar los flujos de audio).

### Paso 2: Verificar o Instalar FFmpeg
La aplicación requiere `ffmpeg` para convertir los flujos de audio descargados al formato MP3. 

1. **Verificación:** La aplicación comprobará si `ffmpeg` está en el PATH del sistema al iniciar. Si no se detecta, se mostrará una advertencia en la interfaz y el botón de descarga se deshabilitará.
2. **Si no lo tienes instalado:**
   * Descarga una versión estable para Windows desde [Gyan.dev](https://www.gyan.dev/ffmpeg/builds/) (se recomienda el archivo *ffmpeg-release-essentials.zip*).
   * Descomprime el archivo y copia la carpeta a una ruta permanente (por ejemplo `C:\ffmpeg`).
   * Añade la ruta de la carpeta `bin` (ej. `C:\ffmpeg\bin`) a tus **Variables de Entorno del Sistema** en el PATH.
   * Reinicia la consola o la aplicación para aplicar los cambios.

*Nota: Hemos verificado que tu sistema actual ya cuenta con una versión funcional de FFmpeg, por lo que este paso ya está cubierto en tu máquina.*

---

## Cómo ejecutar la aplicación

Para iniciar la aplicación, ejecuta el siguiente comando en tu terminal:
```powershell
python app.py
```

---

## Instrucciones de Uso

1. **Pegar URL:** Copia la URL del video de YouTube que deseas y presiona el botón **Pegar Link**. La aplicación buscará en segundo plano los detalles del video (título, canal y duración) y te los mostrará en un recuadro verde.
2. **Seleccionar USB:** Conecta tu memoria USB. Se seleccionará automáticamente. Si tienes varias unidades conectadas, selecciónala desde el menú desplegable. Puedes hacer clic en **Actualizar** en cualquier momento si acabas de conectar una memoria y no aparece.
3. **Autorización Legal:** Lee la declaración legal en el **Paso 3** y marca la casilla de confirmación. El botón **Descargar y Guardar en USB** se activará únicamente cuando confirmes que tienes la autorización correspondiente.
4. **Descarga y Copia:** Presiona el botón verde de descarga. Observarás lo siguiente:
   * **Descargando audio:** Muestra el porcentaje, tamaño y velocidad en tiempo real.
   * **Conversión de formato:** El progreso de conversión a MP3 de alta calidad (192 kbps) a través de FFmpeg.
   * **Copiando a USB:** Una barra que registra la velocidad de copia directa bloque a bloque a tu memoria.
5. **Listo:** Al finalizar, un cuadro emergente te confirmará que el archivo está guardado en tu memoria USB.
