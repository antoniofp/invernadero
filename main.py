import time
import board
import adafruit_dht
import gpiozero
import mysql.connector
from datetime import datetime

# Database connection settings
db_config = {
    'host': 'localhost',
    'user': 'admin',
    'password': 'admin',  
    'database': 'relay_control'
}

def get_relay_state(relay_name):
    """Get the current state of a relay
    Args:
        relay_name (str): Name of the relay
    Returns:
        bool or None: Current state of relay, None if error
    """
    try:
        connection = connect_to_database()
        if connection is None:
            return None
        
        cursor = connection.cursor(dictionary=True)
        
        # Get latest state
        query = """SELECT state FROM relay_states 
                  WHERE relay_name = %s 
                  ORDER BY timestamp DESC LIMIT 1"""
        cursor.execute(query, (relay_name,))
        
        result = cursor.fetchone()
        if result:
            return result['state']
        return None
        
    except mysql.connector.Error as err:
        print(f"Error getting relay state: {err}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

def connect_to_database():
    """Establish database connection"""
    try:
        connection = mysql.connector.connect(**db_config)
        return connection
    except mysql.connector.Error as err:
        print(f"Error connecting to database: {err}")
        return None

# Initialize GPIO for lamp (active_high=False means relay is active LOW)
lampara = gpiozero.OutputDevice(27, active_high=False, initial_value=False)

# Initialize DHT sensor
dhtDevice = adafruit_dht.DHT11(board.D4)
last_temperature_c = 25.0
last_humidity = 50.0

def get_temperature_and_humidity():
    """Read temperature and humidity from DHT sensor"""
    global last_temperature_c
    global last_humidity
    try:
        temperature_c = dhtDevice.temperature
        humidity = dhtDevice.humidity
        last_temperature_c = temperature_c
        last_humidity = humidity
        return temperature_c, humidity
    except:
        return last_temperature_c, last_humidity

# Main loop
while True:
    try:
        # Read the state from database
        db_state = get_relay_state('lamp1')
        
        # If we successfully got a state from the database
        if db_state is not None:
            if db_state:
                print("Turning lamp ON based on database state")
                lampara.on()
            else:
                print("Turning lamp OFF based on database state")
                lampara.off()
        
        # Read and print temperature/humidity
        temperature_c, humidity = get_temperature_and_humidity()
        print(f"Temp: {temperature_c:.1f} C    Humidity: {humidity:.0f}%")
        
        # Wait for 10 seconds before next check
        time.sleep(1)
        
    except KeyboardInterrupt:
        print("\nProgram stopped by user")
        lampara.off()  # Turn off lamp before exiting
        break
    except Exception as e:
        print(f"An error occurred: {e}")
        time.sleep(10)  # Wait before retrying