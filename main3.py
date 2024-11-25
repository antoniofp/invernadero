import time
import board
import adafruit_dht
import gpiozero
import mysql.connector
import minimalmodbus
from datetime import datetime
from threading import Lock

# Database configuration
db_config = {
    'host': 'localhost',
    'user': 'admin',
    'password': 'admin',
    'database': 'INVERNADERO'
}

# Global sensor values with thread safety
values_lock = Lock()
current_values = {
    'air_temperature': None,
    'air_humidity': None,
    'soil_temperature': None,
    'soil_moisture': None,
    'soil_ph': None
}

# Cache for last valid readings
last_valid_values = {
    'air_temperature': 25.0,
    'air_humidity': 50.0,
    'soil_temperature': 25.0,
    'soil_moisture': 50.0,
    'soil_ph': 7.0
}

# Global actuator states
actuator_states = {
    'rele1': False,  # Lamp relay
    'rele2': False,  # Future use
    'riego': False   # Future use
}

# Global device objects
soil_sensor = None
db_connection = None
dht_device = None
lamp_relay = None

def setup_soil_sensor():
    """
    Initialize Modbus soil sensor (JXBS-3001-TR)
    Returns:
        minimalmodbus.Instrument or None: Configured sensor object or None if setup fails
    """
    global soil_sensor
    try:
        soil_sensor = minimalmodbus.Instrument('/dev/ttyUSB0', 1)  # port name, slave address
        
        # Modbus RTU settings according to sensor datasheet
        soil_sensor.serial.baudrate = 9600
        soil_sensor.serial.bytesize = 8
        soil_sensor.serial.parity = 'N'
        soil_sensor.serial.stopbits = 1
        soil_sensor.serial.timeout = 1
        
        print("Soil sensor initialized successfully")
        return soil_sensor
        
    except Exception as e:
        print(f"Error initializing soil sensor: {e}")
        return None

def setup_database():
    """
    Initialize database connection
    Returns:
        mysql.connector.connection or None: Database connection object or None if connection fails
    """
    global db_connection
    try:
        db_connection = mysql.connector.connect(**db_config)
        if db_connection.is_connected():
            print("Database connection established successfully")
            return db_connection
    except mysql.connector.Error as e:
        print(f"Error connecting to database: {e}")
        return None

def setup_hardware():
    """
    Initialize GPIO devices (DHT11 sensor and relay)
    Returns:
        tuple: (dht_device, lamp_relay) or (None, None) if setup fails
    """
    global dht_device, lamp_relay
    try:
        # Initialize DHT11 sensor
        dht_device = adafruit_dht.DHT11(board.D4)
        
        # Initialize lamp relay with active_low=True (relay module is typically active low)
        lamp_relay = gpiozero.OutputDevice(27, active_high=False, initial_value=False)
        
        print("Hardware devices initialized successfully")
        return dht_device, lamp_relay
        
    except Exception as e:
        print(f"Error initializing hardware: {e}")
        return None, None

def log_error(sensor_name, error_message):
    """
    Log errors to database
    Args:
        sensor_name (str): Name of the sensor or system component
        error_message (str): Description of the error
    """
    if db_connection and db_connection.is_connected():
        try:
            cursor = db_connection.cursor()
            query = """
                INSERT INTO errores 
                (nombre_sensor, id_zona, mensaje_error)
                VALUES (%s, %s, %s)
            """
            cursor.execute(query, (sensor_name, 1, error_message))
            db_connection.commit()
            cursor.close()
        except mysql.connector.Error as e:
            print(f"Error logging to database: {e}")

def read_dht11_sensor():
    """
    Read temperature and humidity from DHT11 sensor.
    Updates global current_values and last_valid_values if reading is successful.
    Returns:
        tuple: (temperature, humidity) or (None, None) if reading fails
    """
    global current_values, last_valid_values
    
    try:
        temperature = dht_device.temperature
        humidity = dht_device.humidity
        
        if temperature is not None and humidity is not None:
            with values_lock:
                current_values['air_temperature'] = temperature
                current_values['air_humidity'] = humidity
                # Update last valid values
                last_valid_values['air_temperature'] = temperature
                last_valid_values['air_humidity'] = humidity
            
            return temperature, humidity
            
    except Exception as e:
        error_msg = f"Error reading DHT11: {str(e)}"
        print(error_msg)
        log_error('DHT11', error_msg)
        
        # Return last valid values
        return (last_valid_values['air_temperature'], 
                last_valid_values['air_humidity'])

def read_soil_sensor():
    """
    Read all parameters from soil sensor (temperature, moisture, pH).
    Updates global current_values and last_valid_values if reading is successful.
    Returns:
        tuple: (temperature, moisture, pH) or last valid values if reading fails
    """
    global current_values, last_valid_values
    
    try:
        if soil_sensor is None:
            raise Exception("Soil sensor not initialized")
            
        # Read registers according to sensor datasheet
        temp = soil_sensor.read_register(0x0013) * 0.1    # Temperature
        moisture = soil_sensor.read_register(0x0012) * 0.1  # Moisture
        ph = soil_sensor.read_register(0x0006) * 0.01     # pH
        
        # Validate readings are within reasonable ranges
        if (0 <= temp <= 50 and 
            0 <= moisture <= 100 and 
            0 <= ph <= 14):
            
            with values_lock:
                current_values['soil_temperature'] = temp
                current_values['soil_moisture'] = moisture
                current_values['soil_ph'] = ph
                # Update last valid values
                last_valid_values['soil_temperature'] = temp
                last_valid_values['soil_moisture'] = moisture
                last_valid_values['soil_ph'] = ph
            
            return temp, moisture, ph
            
    except Exception as e:
        error_msg = f"Error reading soil sensor: {str(e)}"
        print(error_msg)
        log_error('Soil_Sensor', error_msg)
        
        # Return last valid values
        return (last_valid_values['soil_temperature'],
                last_valid_values['soil_moisture'],
                last_valid_values['soil_ph'])

def read_all_sensors():
    """
    Read all sensors and update global values.
    Returns:
        dict: Dictionary containing all current sensor values
    """
    # Read DHT11
    air_temp, air_hum = read_dht11_sensor()
    print(f"Air - Temperature: {air_temp:.1f}°C  Humidity: {air_hum:.1f}%")
    
    # Read soil sensor
    soil_temp, soil_moisture, soil_ph = read_soil_sensor()
    print(f"Soil - Temperature: {soil_temp:.1f}°C  Moisture: {soil_moisture:.1f}%  pH: {soil_ph:.2f}")
    
    # Return all current values
    with values_lock:
        return current_values.copy()  # Return a copy to prevent external modification
    
def get_actuator_states():
    """
    Get current states of all actuators from database.
    Updates global actuator_states.
    Returns:
        dict: Current states of all actuators
    """
    global actuator_states
    
    try:
        if not db_connection.is_connected():
            raise mysql.connector.Error("Database connection lost")
            
        cursor = db_connection.cursor(dictionary=True)
        
        # Query each actuator's latest state
        actuator_queries = {
            'rele1': """
                SELECT estado 
                FROM actuador_rele1 
                WHERE id_zona = 1 
                ORDER BY fecha_hora DESC 
                LIMIT 1
            """,
            'rele2': """
                SELECT estado 
                FROM actuador_rele2 
                WHERE id_zona = 1 
                ORDER BY fecha_hora DESC 
                LIMIT 1
            """,
            'riego': """
                SELECT estado 
                FROM actuador_riego 
                WHERE id_zona = 1 
                ORDER BY fecha_hora DESC 
                LIMIT 1
            """
        }
        
        # Update global actuator states
        for actuator, query in actuator_queries.items():
            try:
                cursor.execute(query)
                result = cursor.fetchone()
                if result:
                    actuator_states[actuator] = bool(result['estado'])
            except mysql.connector.Error as e:
                print(f"Error reading {actuator} state: {e}")
                
        cursor.close()
        return actuator_states.copy()
        
    except mysql.connector.Error as e:
        error_msg = f"Database error in get_actuator_states: {str(e)}"
        print(error_msg)
        log_error('Sistema', error_msg)
        return actuator_states.copy()

def log_sensor_data(sensor_data):
    """
    Log all sensor readings to database in one transaction.
    Args:
        sensor_data (dict): Dictionary containing current sensor values
    """
    try:
        if not db_connection.is_connected():
            raise mysql.connector.Error("Database connection lost")
            
        cursor = db_connection.cursor()
        current_time = datetime.now()
        
        # Prepare all insert queries
        queries = [
            # Air temperature
            """INSERT INTO sensor_temperatura 
               (nombre, id_zona, fecha_hora, valor) 
               VALUES (%s, %s, %s, %s)""",
            # Air humidity
            """INSERT INTO sensor_humedad_aire 
               (nombre, id_zona, fecha_hora, valor) 
               VALUES (%s, %s, %s, %s)""",
            # Soil temperature
            """INSERT INTO sensor_temperatura 
               (nombre, id_zona, fecha_hora, valor) 
               VALUES (%s, %s, %s, %s)""",
            # Soil moisture
            """INSERT INTO sensor_humedad_suelo 
               (nombre, id_zona, fecha_hora, valor) 
               VALUES (%s, %s, %s, %s)""",
            # Soil pH
            """INSERT INTO sensor_ph_suelo 
               (nombre, id_zona, fecha_hora, valor) 
               VALUES (%s, %s, %s, %s)"""
        ]
        
        # Prepare data for each query
        data = [
            ('Sensor_Temp_Aire_Z1', 1, current_time, sensor_data['air_temperature']),
            ('Sensor_Hum_Aire_Z1', 1, current_time, sensor_data['air_humidity']),
            ('Sensor_Temp_Suelo_Z1', 1, current_time, sensor_data['soil_temperature']),
            ('Sensor_Hum_Suelo_Z1', 1, current_time, sensor_data['soil_moisture']),
            ('Sensor_PH_Suelo_Z1', 1, current_time, sensor_data['soil_ph'])
        ]
        
        # Execute all queries in a single transaction
        for query, values in zip(queries, data):
            cursor.execute(query, values)
            
        db_connection.commit()
        cursor.close()
        print("Sensor data logged successfully")
        
    except mysql.connector.Error as e:
        error_msg = f"Error logging sensor data: {str(e)}"
        print(error_msg)
        log_error('Sistema', error_msg)
        if db_connection.is_connected():
            db_connection.rollback()

def update_actuator_state(actuator_name, new_state):
    """
    Update physical state of an actuator and log to database.
    Args:
        actuator_name (str): Name of the actuator ('rele1', 'rele2', 'riego')
        new_state (bool): Desired state for the actuator
    """
    try:
        # Update physical actuator
        if actuator_name == 'rele1' and lamp_relay:
            if new_state:
                lamp_relay.on()
                print("Lamp turned ON")
            else:
                lamp_relay.off()
                print("Lamp turned OFF")
        
        # Log state change to database
        if db_connection.is_connected():
            cursor = db_connection.cursor()
            
            # Select appropriate table based on actuator
            table_name = {
                'rele1': 'actuador_rele1',
                'rele2': 'actuador_rele2',
                'riego': 'actuador_riego'
            }.get(actuator_name)
            
            if table_name:
                query = f"""
                    INSERT INTO {table_name}
                    (nombre, id_zona, fecha_hora, estado)
                    VALUES (%s, %s, %s, %s)
                """
                cursor.execute(query, (
                    f'Actuador_{actuator_name}_Z1',
                    1,
                    datetime.now(),
                    new_state
                ))
                db_connection.commit()
                
            cursor.close()
            
    except Exception as e:
        error_msg = f"Error updating {actuator_name}: {str(e)}"
        print(error_msg)
        log_error('Sistema', error_msg)

import threading
import time
from queue import Queue
from datetime import datetime

# Global control flags
running = True
sensor_data_queue = Queue()

def sensor_reading_thread():
    """Thread function to continuously read sensors"""
    global running
    
    while running:
        try:
            # Read all sensors and put data in queue
            sensor_data = read_all_sensors()
            sensor_data_queue.put(sensor_data)
            time.sleep(5)  # Read sensors every 5 seconds
            
        except Exception as e:
            error_msg = f"Error in sensor reading thread: {str(e)}"
            print(error_msg)
            log_error('Sistema', error_msg)
            time.sleep(5)  # Wait before retry

def database_update_thread():
    """Thread function to periodically update database"""
    global running
    last_upload_time = time.time()
    
    while running:
        try:
            current_time = time.time()
            
            # Upload to database every 20 seconds
            if current_time - last_upload_time >= 5:
                if not sensor_data_queue.empty():
                    sensor_data = sensor_data_queue.get()
                    log_sensor_data(sensor_data)
                    last_upload_time = current_time
                    
            # Get actuator states from database
            actuator_states = get_actuator_states()
            # Update physical actuator states
            for actuator, state in actuator_states.items():
                update_actuator_state(actuator, state)
                
            time.sleep(1)  # Check every second
            
        except Exception as e:
            error_msg = f"Error in database update thread: {str(e)}"
            print(error_msg)
            log_error('Sistema', error_msg)
            time.sleep(5)

def setup_component(setup_func, component_name, max_retries=3):
    """
    Generic setup function with retries
    Returns:
        Component object or None if all retries fail
    """
    for attempt in range(max_retries):
        try:
            component = setup_func()
            if component:
                print(f"{component_name} initialized successfully")
                return component
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries} failed for {component_name}: {e}")
            
        if attempt < max_retries - 1:  # Don't sleep on last attempt
            time.sleep(5)
            
    print(f"Failed to initialize {component_name} after {max_retries} attempts")
    return None

def main():
    global running, soil_sensor, db_connection, dht_device, lamp_relay
    
    try:
        # Initial setup with retries
        print("Initializing components...")
        
        # Setup database
        db_connection = setup_component(
            setup_database,
            "Database connection"
        )
        if not db_connection:
            raise Exception("Failed to initialize database connection")
            
        # Setup soil sensor
        soil_sensor = setup_component(
            setup_soil_sensor,
            "Soil sensor"
        )
        if not soil_sensor:
            raise Exception("Failed to initialize soil sensor")
            
        # Setup hardware
        dht_result, lamp_result = setup_component(
            setup_hardware,
            "Hardware devices"
        )
        if not dht_result or not lamp_result:
            raise Exception("Failed to initialize hardware devices")
            
        dht_device = dht_result
        lamp_relay = lamp_result
        
        print("All components initialized successfully")
        
        # Start threads
        sensor_thread = threading.Thread(target=sensor_reading_thread)
        db_thread = threading.Thread(target=database_update_thread)
        
        sensor_thread.daemon = True
        db_thread.daemon = True
        
        sensor_thread.start()
        db_thread.start()
        
        # Main loop - just keep the program running and handle keyboard interrupt
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        running = False  # Signal threads to stop
        
    except Exception as e:
        error_msg = f"Critical error in main loop: {str(e)}"
        print(error_msg)
        log_error('Sistema', error_msg)
        running = False
        
    finally:
        # Cleanup
        running = False
        
        # Wait for threads to finish
        if 'sensor_thread' in locals() and sensor_thread.is_alive():
            sensor_thread.join(timeout=2)
        if 'db_thread' in locals() and db_thread.is_alive():
            db_thread.join(timeout=2)
            
        # Clean up hardware
        if lamp_relay:
            lamp_relay.off()  # Ensure lamp is off
            lamp_relay.close()
            
        # Close database connection
        if db_connection and db_connection.is_connected():
            db_connection.close()
            
        print("Cleanup completed")

if __name__ == "__main__":
    main()
"""
alias supy='sudo -E env PATH=$PATH python3'

supy main3.py

"""