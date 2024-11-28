from picamera2 import Picamera2
from libcamera import controls
import torch
import time
from flask import Flask, jsonify, send_file
import os
from datetime import datetime
import shutil

# Directory Configuration
BASE_DIR = "camera_images"
CAPTURE_DIR = os.path.join(BASE_DIR, "captures")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")

# Ensure directories exist
for dir_path in [CAPTURE_DIR, PROCESSED_DIR]:
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

# Initialize camera with autofocus
picam2 = Picamera2()
camera_config = picam2.create_still_configuration(main={"size": (1280, 720)})
picam2.configure(camera_config)

# Enable continuous autofocus
picam2.set_controls({"AfMode": controls.AfModeEnum.Continuous})
picam2.start()
time.sleep(2)  # Warm-up time

# Load YOLO model
from ultralytics import YOLO
MODEL_PATH = "best_model.pt"
model = YOLO(MODEL_PATH)

# Flask app
app = Flask(__name__)

def keep_only_latest_file(directory):
    """Keep only the most recent file in the specified directory."""
    files = [os.path.join(directory, f) for f in os.listdir(directory) 
             if os.path.isfile(os.path.join(directory, f))]
    if files:
        # Sort files by modification time
        files.sort(key=os.path.getmtime)
        # Remove all but the latest file
        for f in files[:-1]:
            os.remove(f)

def capture_and_process():
    """Capture and process a new image, keeping only the latest files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Capture image
    capture_path = os.path.join(CAPTURE_DIR, f"capture_{timestamp}.jpg")
    picam2.capture_file(capture_path)
    
    # Process with YOLO
    processed_path = os.path.join(PROCESSED_DIR, f"processed_{timestamp}.jpg")
    results = model(capture_path, save=True)
    
    # Move the YOLO output to our processed directory
    yolo_output = os.path.join("runs", "detect", "predict", f"capture_{timestamp}.jpg")
    if os.path.exists(yolo_output):
        shutil.move(yolo_output, processed_path)
        # Clean up YOLO's runs directory
        shutil.rmtree("runs/detect", ignore_errors=True)
    
    # Keep only latest files
    keep_only_latest_file(CAPTURE_DIR)
    keep_only_latest_file(PROCESSED_DIR)
    
    return capture_path, processed_path

@app.route('/latest-capture', methods=['GET'])
def get_latest_capture():
    """Endpoint to get the latest captured image."""
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
    """Endpoint to get the latest processed image with predictions."""
    try:
        files = os.listdir(PROCESSED_DIR)
        if not files:
            return jsonify({"error": "No processed images available"}), 404
        latest_file = max(files, key=lambda x: os.path.getmtime(os.path.join(PROCESSED_DIR, x)))
        return send_file(os.path.join(PROCESSED_DIR, latest_file), mimetype='image/jpeg')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def main():
    print("[INFO] Starting camera service...")
    
    # Run Flask in a separate thread
    from threading import Thread
    flask_thread = Thread(target=lambda: app.run(host='0.0.0.0', port=5000))
    flask_thread.daemon = True
    flask_thread.start()
    
    # Main capture loop
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