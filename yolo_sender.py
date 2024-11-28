from picamera2 import Picamera2
from libcamera import controls
import torch
import time
from flask import Flask, jsonify, send_file
import os
from datetime import datetime
import shutil
from threading import Thread
from ultralytics import YOLO

# Directorios de configuración
BASE_DIR = "camera_images"
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")

# Asegurar que los directorios existan
os.makedirs(CAPTURE_DIR, exist_ok=True)
os.makedirs(PROCESSED_DIR, exist_ok=True)

# Inicializar la cámara con enfoque automático
picam2 = Picamera2()
camera_config = picam2.create_still_configuration(main={"size": (1280, 720)})
picam2.configure(camera_config)
picam2.set_controls({"AfMode": controls.AfModeEnum.Continuous})
picam2.start()
time.sleep(2)  # Calentamiento de la cámara

# Cargar modelo YOLO
MODEL_PATH = "best_model.pt"
model = YOLO(MODEL_PATH)

# Crear la app Flask
app = Flask(__name__)

# Funciones de manejo de imágenes
def keep_only_latest_file(directory):
    files = [os.path.join(directory, f) for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
    if files:
        files.sort(key=os.path.getmtime)
        for f in files[:-1]:
            os.remove(f)

def capture_and_process():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    capture_path = os.path.join(CAPTURE_DIR, f"capture_{timestamp}.jpg")
    picam2.capture_file(capture_path)

    # Procesar imagen con el modelo YOLO
    results = model(capture_path, save=True)
    yolo_output = results.save_dir / f"capture_{timestamp}.jpg"
    processed_path = os.path.join(PROCESSED_DIR, f"processed_{timestamp}.jpg")

    if os.path.exists(yolo_output):
        shutil.move(yolo_output, processed_path)
        shutil.rmtree("runs/detect", ignore_errors=True)

    keep_only_latest_file(CAPTURE_DIR)
    keep_only_latest_file(PROCESSED_DIR)

    return capture_path, processed_path

# Rutas de Flask
@app.route('/latest-capture', methods=['GET'])
def get_latest_capture():
    try:
        files = os.listdir(CAPTURE_DIR)
        if not files:
            return jsonify({"error": "No captures available"}), 404
        latest_file = max(files, key=lambda x: os.path.getmtime(os.path.join(CAPTURE_DIR, x)))
        return send_file(os.path.join(CAPTURE_DIR, latest_file), mimetype='image/jpeg')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/latest-processed', methods=['GET'])
def get_latest_processed():
    try:
        files = os.listdir(PROCESSED_DIR)
        if not files:
            return jsonify({"error": "No processed images available"}), 404
        latest_file = max(files, key=lambda x: os.path.getmtime(os.path.join(PROCESSED_DIR, x)))
        return send_file(os.path.join(PROCESSED_DIR, latest_file), mimetype='image/jpeg')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Función para ejecutar el servidor Flask y capturar imágenes
def main():
    print("[INFO] Starting camera service...")

    # Ejecutar Flask en un hilo separado
    flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=5000))
    flask_thread.daemon = True
    flask_thread.start()

    # Bucle principal de captura y procesamiento
    while True:
        try:
            capture_and_process()
            print("[INFO] Image captured and processed successfully")
        except Exception as e:
            print(f"[ERROR] An error occurred: {e}")
        time.sleep(20)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Shutting down camera service...")
        picam2.stop()