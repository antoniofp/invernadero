from picamera2 import Picamera2
import requests
import time
import os
from datetime import datetime

# Initialize the camera
picam2 = Picamera2()
# Configure camera for 1280x720 resolution
camera_config = picam2.create_still_configuration(main={"size": (1280, 720)})
picam2.configure(camera_config)
picam2.start()

# Allow camera to warm up
time.sleep(2)

# URL where we'll send the images (replace with your laptop's IP)
SERVER_URL = "http://192.168.X.X:8000/upload"  # Replace X.X with your laptop's IP
TEMP_IMAGE = "temp_image.jpg"

def capture_and_send():
    try:
        # Capture image
        picam2.capture_file(TEMP_IMAGE)
        print(f"[{datetime.now()}] Image captured")

        # Prepare the file for sending
        with open(TEMP_IMAGE, 'rb') as img_file:
            files = {'image': ('image.jpg', img_file, 'image/jpeg')}
            
            # Try to send the image
            response = requests.post(SERVER_URL, files=files)
            
            # Check if send was successful
            if response.status_code == 200:
                print(f"[{datetime.now()}] Image sent successfully")
                return True
            else:
                print(f"[{datetime.now()}] Failed to send image. Status code: {response.status_code}")
                return False

    except requests.exceptions.RequestException as e:
        print(f"[{datetime.now()}] Network error: {str(e)}")
        return False
    except Exception as e:
        print(f"[{datetime.now()}] Unexpected error: {str(e)}")
        return False
    finally:
        # Clean up: delete the temporary image if it exists
        if os.path.exists(TEMP_IMAGE):
            os.remove(TEMP_IMAGE)

def main():
    print("Starting camera service...")
    
    while True:
        success = False
        while not success:
            success = capture_and_send()
            if not success:
                print(f"[{datetime.now()}] Retrying in 5 seconds...")
                time.sleep(5)
        
        # Wait 20 seconds before next capture
        time.sleep(20)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nShutting down camera service...")
        picam2.stop()
