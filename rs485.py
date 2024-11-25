import minimalmodbus
import time

# Initialize the sensor
sensor = minimalmodbus.Instrument('/dev/ttyUSB0', 1)

# Turn on debug mode to see the communication
minimalmodbus._print_out = True
sensor.debug = True

# Communication settings
sensor.serial.baudrate = 9600        
sensor.serial.bytesize = 8
sensor.serial.parity = 'N'           
sensor.serial.stopbits = 1
sensor.serial.timeout = 1            

def read_single_value(register):
    try:
        print(f"\nTrying to read register {register} (0x{register:02X}):")
        value = sensor.read_register(register)
        return value
    except Exception as e:
        print(f"Error reading register {register}: {e}")
        return None

# Test reading each register
print("Testing individual registers...")
for register in [0x13, 0x12, 0x100]:
    value = read_single_value(register)
    print(f"Register {register}: {value}")
    time.sleep(1)