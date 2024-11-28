# Import required libraries
import time
import board
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

try:
    # Create the I2C bus
    i2c = busio.I2C(board.SCL, board.SDA)

    # Create the ADC object using the I2C bus
    ads = ADS.ADS1115(i2c)

    # Create single-ended input on channel 0
    chan = AnalogIn(ads, ADS.P0)
    
    print("Starting photoresistor readings...")
    print("-" * 50)
    print("Press CTRL+C to exit")
    print("-" * 50)

    while True:
        # Read the value and voltage
        raw_value = chan.value
        voltage = chan.voltage

        # Print formatted output
        print(f"Raw Value: {raw_value}")
        print(f"Voltage: {voltage:.2f}V")
        print("-" * 30)
        
        # Wait for 3 seconds before next reading
        time.sleep(3)

except KeyboardInterrupt:
    print("\nProgram stopped by user")
    
except Exception as e:
    print(f"An error occurred: {str(e)}")
    
finally:
    # This will run on exit
    print("Cleaning up...")