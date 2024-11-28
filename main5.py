import time
import board
import adafruit_dht
import gpiozero
import mysql.connector
import minimalmodbus
from datetime import datetime
from threading import Lock
import busio
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
from yolo_sender import capture_and_process

# Configurable intervals (in seconds)
SENSOR_READ_INTERVAL = 5
ACTUATOR_CHECK_INTERVAL = 1

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
    'soil_ph': None,
    'light_intensity' : None
}

# Cache for last valid readings
last_valid_values = {
    'air_temperature': 25.0,
    'air_humidity': 50.0,
    'soil_temperature': 25.0,
    'soil_moisture': 50.0,
    'soil_ph': 7.0,
    'light_intensity' : 50.0
}

# Global actuator states with cache for state tracking
actuator_states = {
    'rele1': False,  # Lamp relay
    'rele2': False,  # Fan relay
    'rele3': False,  # Humidifier relay
    'riego': False   # valve servo
}

actuator_states_cache = {
    'rele1': None,
    'rele2': None,
    'rele3': None,
    'riego': None
}

# Environmental control parameters (will be updated from database)
env_parameters = {
    'max_temp': 30.0,
    'min_air_humidity': 50.0,
    'min_soil_moisture': 30.0,
    'db_update_time': 60  # Default 5 minutes in seconds
}

# Global device objects
soil_sensor = None
db_connection = None
dht_device = None
lamp_relay = None
fan_relay = None
humidifier_relay = None
irrigation_servo = None
light_sensor = None


def setup_soil_sensor():
    """Initialize Modbus soil sensor (JXBS-3001-TR)"""
    global soil_sensor
    try:
        soil_sensor = minimalmodbus.Instrument('/dev/ttyUSB0', 1)
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
    """Initialize database connection"""
    global db_connection
    try:
        db_connection = mysql.connector.connect(**db_config)
        if db_connection.is_connected():
            print("Database connection established successfully")
            return db_connection
    except mysql.connector.Error as e:
        print(f"Error connecting to database: {e}")
        return None

#sets up dht11 sensor and relays, and servo
def setup_hardware():
    """Initialize GPIO devices (sensors and actuators)"""
    global dht_device, lamp_relay, fan_relay, humidifier_relay, irrigation_servo, light_sensor
    try:
        # Initialize DHT11 sensor
        dht_device = adafruit_dht.DHT11(board.D4)

        # Initialize ADS1115 ADC
        i2c = busio.I2C(board.SCL, board.SDA)
        ads = ADS.ADS1115(i2c, address=0x49)
        light_sensor = AnalogIn(ads, ADS.P0)
        
        # Initialize relays (active_high=False for active-low relay modules)
        lamp_relay = gpiozero.OutputDevice(27, active_high=False, initial_value=False)
        fan_relay = gpiozero.OutputDevice(22, active_high=False, initial_value=False)
        humidifier_relay = gpiozero.OutputDevice(23, active_high=False, initial_value=False)
        
        # Initialize servo for irrigation
        irrigation_servo = gpiozero.Servo(12)
        # Ensure servo starts at 0 position
        irrigation_servo.min()
        
        print("Hardware devices initialized successfully")
        return (dht_device, lamp_relay, fan_relay, humidifier_relay, irrigation_servo)
    except Exception as e:
        print(f"Error initializing hardware: {e}")
        return (None, None, None, None, None)

db_lock = Lock()

def update_env_parameters():
    """Update environmental parameters from database"""
    global env_parameters
    cursor = None
    with db_lock:
        try:
            if not db_connection.is_connected():
                db_connection.reconnect()
            
            cursor = db_connection.cursor(dictionary=True)
            query = """
                SELECT max_temp, min_air_humidity, min_soil_moisture, db_update_time
                FROM zona
                WHERE id_zona = 1
            """
            cursor.execute(query)
            result = cursor.fetchone()
            
            if result:
                env_parameters.update({
                    'max_temp': float(result['max_temp']),
                    'min_air_humidity': float(result['min_air_humidity']),
                    'min_soil_moisture': float(result['min_soil_moisture']),
                    'db_update_time': int(result['db_update_time'])
                })
                print("Environmental parameters updated successfully")
        except Exception as e:
            error_msg = f"Error updating environmental parameters: {e}"
            print(error_msg)
            log_error('Sistema', error_msg)
        finally:
            if cursor:
                cursor.close()

def read_dht11_sensor():
    """Read temperature and humidity from DHT11 sensor."""
    global current_values, last_valid_values
    
    try:
        temperature = dht_device.temperature
        humidity = dht_device.humidity
        
        if temperature is not None and humidity is not None:
            with values_lock:
                current_values['air_temperature'] = temperature
                current_values['air_humidity'] = humidity
                last_valid_values['air_temperature'] = temperature
                last_valid_values['air_humidity'] = humidity
            
            return temperature, humidity
            
    except Exception as e:
        error_msg = f"Error reading DHT11: {str(e)}"
        print(error_msg)
        log_error('DHT11', error_msg)
        return (last_valid_values['air_temperature'], 
                last_valid_values['air_humidity'])

def read_light_sensor():
    """Read light intensity from ADS1115 ADC with photoresistor."""
    global current_values, last_valid_values
    
    try:
        if light_sensor is None:
            raise Exception("Light sensor not initialized")
            
        # Read voltage value (0V to 5V)
        voltage = light_sensor.voltage
        
        # Convert to percentage (assuming higher voltage means more light)
        # Map 0-5V to 0-100%
        light_intensity = (voltage / 3.3) * 100
        
        # Validate reading is in expected range
        if 0 <= light_intensity <= 100:
            with values_lock:
                current_values['light_intensity'] = light_intensity
                last_valid_values['light_intensity'] = light_intensity
            
            return light_intensity
            
    except Exception as e:
        error_msg = f"Error reading light sensor: {str(e)}"
        print(error_msg)
        log_error('Light_Sensor', error_msg)
        return last_valid_values['light_intensity']
    
def read_soil_sensor():
    """Read all parameters from soil sensor."""
        
    global current_values, last_valid_values
    
    try:
        if soil_sensor is None:
            raise Exception("Soil sensor not initialized")
            
        temp = soil_sensor.read_register(0x0013) * 0.1    # Temperature
        moisture = soil_sensor.read_register(0x0012) * 0.1  # Moisture
        ph = soil_sensor.read_register(0x0006) * 0.01     # pH
        
        if (0 <= temp <= 50 and 
            0 <= moisture <= 100 and 
            0 <= ph <= 14):
            
            with values_lock:
                current_values['soil_temperature'] = temp
                current_values['soil_moisture'] = moisture
                current_values['soil_ph'] = ph
                last_valid_values['soil_temperature'] = temp
                last_valid_values['soil_moisture'] = moisture
                last_valid_values['soil_ph'] = ph
            
            return temp, moisture, ph
            
    except Exception as e:
        error_msg = f"Error reading soil sensor: {str(e)}"
        print(error_msg)
        log_error('Soil_Sensor', error_msg)
        return (last_valid_values['soil_temperature'],
                last_valid_values['soil_moisture'],
                last_valid_values['soil_ph'])

def read_all_sensors():
    """Read all sensors and update global values."""
    # Read DHT11
    air_temp, air_hum = read_dht11_sensor()
    print(f"Air - Temperature: {air_temp:.1f} C  Humidity: {air_hum:.1f}%")
    
    # Read soil sensor
    soil_temp, soil_moisture, soil_ph = read_soil_sensor()
    print(f"Soil - Temperature: {soil_temp:.1f} C  Moisture: {soil_moisture:.1f}%  pH: {soil_ph:.2f}")
    
    # Read light sensor
    light_intensity = read_light_sensor()
    print(f"Light Intensity: {light_intensity:.1f}%")
    
    with values_lock:
        return current_values.copy()

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
            'rele3': """
                SELECT estado 
                FROM actuador_rele3 
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
                    # Update physical state if different from database
                    if actuator_states_cache[actuator] != actuator_states[actuator]:
                        update_actuator_state(actuator, actuator_states[actuator])
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
            """INSERT INTO sensor_temperatura_suelo
               (nombre, id_zona, fecha_hora, valor) 
               VALUES (%s, %s, %s, %s)""",
            # Soil moisture
            """INSERT INTO sensor_humedad_suelo 
               (nombre, id_zona, fecha_hora, valor) 
               VALUES (%s, %s, %s, %s)""",
            # Soil pH
            """INSERT INTO sensor_ph_suelo 
               (nombre, id_zona, fecha_hora, valor) 
               VALUES (%s, %s, %s, %s)""",
            # Light intensity
            """INSERT INTO sensor_intensidad_luz 
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
            ('Sensor_Luz_Z1', 1, current_time, sensor_data['light_intensity'])
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
                INSERT INTO sensor_error_log 
                (nombre_sensor, id_zona, mensaje_error)
                VALUES (%s, %s, %s)
            """
            cursor.execute(query, (sensor_name, 1, error_message))
            db_connection.commit()
            cursor.close()
        except mysql.connector.Error as e:
            print(f"Error logging to database: {e}")

def update_actuator_state(actuator_name, new_state):
    """Update physical state of an actuator and log to database if state has changed."""
    global actuator_states_cache
    
    # Check if state has actually changed
    if actuator_states_cache[actuator_name] == new_state:
        return
        
    try:
        # Update physical actuator
        if actuator_name == 'rele1' and lamp_relay:
            lamp_relay.value = new_state
        elif actuator_name == 'rele2' and fan_relay:
            fan_relay.value = new_state
        elif actuator_name == 'rele3' and humidifier_relay:
            humidifier_relay.value = new_state
        elif actuator_name == 'riego' and irrigation_servo:
            if new_state:
                irrigation_servo.mid()  # 90 degrees position
            else:
                irrigation_servo.min()  # 0 degrees position
        
        # Update cache
        actuator_states_cache[actuator_name] = new_state
        
        # Log state change to database
        if db_connection.is_connected():
            cursor = db_connection.cursor()
            
            table_name = {
                'rele1': 'actuador_rele1',
                'rele2': 'actuador_rele2',
                'rele3': 'actuador_rele3',
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

def check_environmental_conditions():
    """Check sensor values against thresholds and control actuators accordingly."""
    with values_lock:
        air_temp = current_values['air_temperature']
        air_humidity = current_values['air_humidity']
        soil_moisture = current_values['soil_moisture']
    
    try:
        # Temperature control - Fan
        if air_temp > env_parameters['max_temp']:
            update_actuator_state('rele2', True)  # Turn on fan
        else:
            update_actuator_state('rele2', False)  # Turn off fan
        
        # Air humidity control - Humidifier
        if air_humidity < env_parameters['min_air_humidity']:
            update_actuator_state('rele3', True)  # Turn on humidifier
        else:
            update_actuator_state('rele3', False)  # Turn off humidifier
        
        # Soil moisture control - Irrigation
        if soil_moisture < env_parameters['min_soil_moisture']:
            update_actuator_state('riego', True)  # Turn on irrigation
        else:
            update_actuator_state('riego', False)  # Turn off irrigation
            
    except Exception as e:
        error_msg = f"Error in environmental control: {str(e)}"
        print(error_msg)
        log_error('Sistema', error_msg)

def calculate_24h_average_temp():
    """Calculate average temperature from last 24 hours"""
    with db_lock:
        try:
            if not db_connection.is_connected():
                db_connection.reconnect()
                
            cursor = db_connection.cursor(dictionary=True)
            
            # Get temperatures from last 24 hours
            query = """
                SELECT valor
                FROM sensor_temperatura
                WHERE id_zona = 1 
                AND fecha_hora >= NOW() - INTERVAL 24 HOUR
            """
            cursor.execute(query)
            temperatures = cursor.fetchall()
            cursor.close()
            
            if temperatures:
                # Calculate average temperature
                avg_temp = sum(record['valor'] for record in temperatures) / len(temperatures)
                return avg_temp
            return None
            
        except Exception as e:
            error_msg = f"Error calculating 24h average temperature: {e}"
            print(error_msg)
            log_error('Sistema', error_msg)
            return None


#aquí se calcula el gdd diario, se actualiza el gdd acumulado y se estima el tiempo hasta la cosecha
#aquí se define la temperatura base en 10°C
def update_gdd_and_harvest_estimate():
    """
    Calculate daily GDD, update cumulative GDD and estimate days until harvest.
    Base temperature is 10°C.
    """
    with db_lock:
        try:
            if not db_connection.is_connected():
                db_connection.reconnect()
                
            cursor = db_connection.cursor(dictionary=True)
            
            # First get current GDD and GDD needed for harvest
            query = """
                SELECT gdd, gdd_for_harvest
                FROM zona
                WHERE id_zona = 1
            """
            cursor.execute(query)
            result = cursor.fetchone()
            
            if not result:
                cursor.close()
                return
                
            current_gdd = result['gdd'] if result['gdd'] else 0
            gdd_for_harvest = result['gdd_for_harvest']
            
            # Calculate today's GDD
            avg_temp = calculate_24h_average_temp()
            if avg_temp is None:
                cursor.close()
                return
                
            # Calculate GDD for today (simple method)
            daily_gdd = max(0, avg_temp - 10)  # Base temp is 10°C
            
            # Add to cumulative GDD
            new_total_gdd = current_gdd + daily_gdd
            
            # Calculate estimated days until harvest
            if daily_gdd > 0:
                remaining_gdd = gdd_for_harvest - new_total_gdd
                est_days = remaining_gdd / daily_gdd if remaining_gdd > 0 else 0
            else:
                est_days = None
                
            # Update the database
            update_query = """
                UPDATE zona
                SET gdd = %s,
                    est_days_harvest = %s
                WHERE id_zona = 1
            """
            cursor.execute(update_query, (new_total_gdd, est_days))
            db_connection.commit()
            cursor.close()
            
            print(f"Updated GDD: {new_total_gdd:.2f}, Estimated days until harvest: {est_days:.1f if est_days else 'N/A'}")
            
        except Exception as e:
            error_msg = f"Error updating GDD and harvest estimate: {e}"
            print(error_msg)
            log_error('Sistema', error_msg)

import threading

# Global control flags
running = True

#read sensors and update greenhouse activation parameters
#update greenhouse actuators irl
def sensor_reading_thread():
    """Thread function to continuously read sensors"""
    global running
    
    while running:
        try:
            # Read all sensors, update global values
            read_all_sensors()
            # Check and update environmental controls, modify global actuator states
            check_environmental_conditions()
            
            time.sleep(SENSOR_READ_INTERVAL)
            
        except Exception as e:
            error_msg = f"Error in sensor reading thread: {str(e)}"
            print(error_msg)
            log_error('Sistema', error_msg)
            time.sleep(5)  # Wait before retry

#uploads sensor data to database every db_update_time seconds, and updates environmental parameters every 5 minutes
#gets actuator states from database every ACTUATOR_CHECK_INTERVAL seconds
def database_update_thread():
    """Thread function to handle database operations"""
    global running

    last_upload_time = time.time()
    last_params_update = time.time()
    last_gdd_update = None  # Track last GDD update
    
    while running:
        try:
            current_time = time.time()
            current_datetime = datetime.now()
            
            # Update environmental parameters every 5 minutes
            if current_time - last_params_update >= 300:
                update_env_parameters()
                last_params_update = current_time
            
            # Upload to database based on db_update_time from zone
            if current_time - last_upload_time >= env_parameters['db_update_time']:
                with values_lock:
                    sensor_data = current_values.copy()
                log_sensor_data(sensor_data)
                last_upload_time = current_time
            
            # Update GDD at noon each day
            current_hour = current_datetime.hour
            current_date = current_datetime.date()
            
            if (current_hour == 12 and 
                (last_gdd_update is None or last_gdd_update != current_date)):
                update_gdd_and_harvest_estimate()
                last_gdd_update = current_date
                    
            # Get actuator states from database
            get_actuator_states()
            
            time.sleep(ACTUATOR_CHECK_INTERVAL)
            
        except Exception as e:
            error_msg = f"Error in database update thread: {str(e)}"
            print(error_msg)
            log_error('Sistema', error_msg)
            time.sleep(5)
#function para actualizar foto
def photo_capture_thread():
    """Thread function to handle periodic photo capture and processing."""
    global running
    last_photo_capture = time.time()
    capture_interval = 300  # Intervalo de captura en segundos (e.g., 5 minutos)

    while running:
        try:
            current_time = time.time()
            
            # Capturar y procesar fotos en intervalos especificados
            if current_time - last_photo_capture >= capture_interval:
                print("[INFO] Capturing and processing photo...")
                capture_and_process()  # Llama a la función del yolo_sender.py
                last_photo_capture = current_time

            time.sleep(1)  # Pausa breve para evitar espera activa
        except Exception as e:
            print(f"[ERROR] Photo capture thread error: {e}")
            time.sleep(5)  # Espera antes de reintentar en caso de error

#function to close gpio connections, idk what happens if i dont do it
def cleanup_hardware():
    """Safely cleanup all hardware devices"""
    try:
        # Turn off all actuators
        if lamp_relay:
            lamp_relay.off()
            lamp_relay.close()
        if fan_relay:
            fan_relay.off()
            fan_relay.close()
        if humidifier_relay:
            humidifier_relay.off()
            humidifier_relay.close()
        if irrigation_servo:
            irrigation_servo.min()  # Return to 0 position
            irrigation_servo.close()
            
        # Add DHT cleanup
        if dht_device:
            dht_device.exit()
    
            
        # Add soil sensor cleanup
        if soil_sensor:
            soil_sensor.serial.close()
            
    except Exception as e:
        print(f"Error during hardware cleanup: {e}")

#function to setup sensors and hardware with retries using the component name and its setup function
#returns object to that component
def setup_component(setup_func, component_name, max_retries=3):
    """Generic setup function with retries"""
    for attempt in range(max_retries):
        try:
            component = setup_func()
            if component:
                print(f"{component_name} initialized successfully")
                return component
        except Exception as e:
            print(f"Attempt {attempt + 1}/{max_retries} failed for {component_name}: {e}")
            
        if attempt < max_retries - 1:
            time.sleep(5)
            
    print(f"Failed to initialize {component_name} after {max_retries} attempts")
    return None

def main():
    global running, soil_sensor, db_connection, dht_device
    global lamp_relay, fan_relay, humidifier_relay, irrigation_servo, light_sensor  # Add light_sensor
    
    try:
        print("Initializing components...")
        
        # Setup database
        db_connection = setup_component(
            setup_database,
            "Database connection"
        )
        if not db_connection:
            raise Exception("Failed to initialize database connection")
        
        # Get initial environmental parameters
        update_env_parameters()
            
        # Setup soil sensor
        soil_sensor = setup_component(
            setup_soil_sensor,
            "Soil sensor"
        )
        if not soil_sensor:
            raise Exception("Failed to initialize soil sensor")
            
        # Setup hardware
        hw_results = setup_component(
            setup_hardware,
            "Hardware devices"
        )
        if not all(hw_results):
            raise Exception("Failed to initialize hardware devices")
            
        # Update this line to include light_sensor
        dht_device, lamp_relay, fan_relay, humidifier_relay, irrigation_servo, light_sensor = hw_results
        
        print("All components initialized successfully")
        
        # Start threads
        sensor_thread = threading.Thread(target=sensor_reading_thread)
        time.sleep(0.1)  # maybe with this the threads dont go stupid
        db_thread = threading.Thread(target=database_update_thread)
        photo_thread = threading.Thread(target=photo_capture_thread)
        
        # Set threads as daemon so they will automatically close when the main program exits
        sensor_thread.daemon = True
        db_thread.daemon = True
        photo_thread.daemon = True
        
        sensor_thread.start()
        db_thread.start()
        photo_thread.start()
        
        # Main loop
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nPrograma detenido, esperando a que terminen de ejecutarse las threads")
        running = False
        
    except Exception as e:
        error_msg = f"Error masivo, reinicia todo porfa: {str(e)}"
        print(error_msg)
        log_error('Sistema', error_msg)
        running = False
        
    finally:
        # Cleanup
        running = False
        
        # Wait for threads to finish
        if 'sensor_thread' in locals() and sensor_thread.is_alive():
            sensor_thread.join(timeout=6)  
        if 'db_thread' in locals() and db_thread.is_alive():
            db_thread.join(timeout=6)  
        if 'photo_thread' in locals() and photo_thread.is_alive():  
            photo_thread.join(timeout=6)
        
        cleanup_hardware()
            
        # Close database connection
        if db_connection and db_connection.is_connected():
            db_connection.close()
            
        print("Todo cerrado, bye")

if __name__ == "__main__":
    main()


# Para ejecutar el programa, se puede usar el siguiente script de bash:
"""
    
alias supy='sudo -E env PATH=$PATH python3'

supy main4.py

"""