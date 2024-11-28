from gpiozero import Servo
from time import sleep

# Create servo object - GPIO12 (Pin 32)
servo = Servo(12, frame_width=0.005)

try:
    while True:
        # Get user input as percentage
        user_input = input("Enter position (0-100%), or 'q' to quit: ")
        
        # Check for quit command
        if user_input.lower() == 'q':
            break
            
        try:
            # Convert input to float and validate range
            position = float(user_input)
            if position < 0 or position > 100:
                print("Please enter a number between 0 and 100")
                continue
                
            # Convert percentage to servo value (-1 to 1)
            # 0% = -1 (fully left/closed)
            # 50% = 0 (middle)
            # 100% = 1 (fully right/open)
            servo_value = (position / 50) - 1
            
            # Move servo
            servo.value = servo_value
            print(f"Moved to {position}% (servo value: {servo_value:.2f})")
            
        except ValueError:
            print("Please enter a valid number")
            
except KeyboardInterrupt:
    print("\nExiting...")
    
finally:
    # Cleanup
    servo.detach()