import time
import board
import adafruit_dht
import gpiozero
import mysql.connector
import minimalmodbus
from datetime import datetime

# Database configuration
db_config = {
    'host': 'localhost',
    'user': 'admin',
    'password': 'admin',
    'database': 'INVERNADERO'
}

# Global database connection
conexion = None

# Initialize soil sensor
try:
    soil_sensor = minimalmodbus.Instrument('/dev/ttyUSB0', 1)
    soil_sensor.serial.baudrate = 9600        
    soil_sensor.serial.bytesize = 8
    soil_sensor.serial.parity = 'N'           
    soil_sensor.serial.stopbits = 1
    soil_sensor.serial.timeout = 1   
except Exception as e:
    print(f"Error inicial configurando sensor de suelo: {e}")
    soil_sensor = None

def ensure_connection():
    """Ensures database connection is active, reconnects if needed"""
    global conexion
    try:
        if conexion is None or not conexion.is_connected():
            print("Database connection lost. Attempting to reconnect...")
            try:
                conexion = mysql.connector.connect(**db_config)
                print("Successfully reconnected to database")
            except mysql.connector.Error as err:
                print(f"Failed to reconnect: {err}")
                time.sleep(5)  
                return False
        return True
    except mysql.connector.Error:
        return False

def execute_read_query(query):
    """Executes a SELECT query and returns results"""
    if not ensure_connection():
        return None
    try:
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(query)
        result = cursor.fetchall()
        cursor.close()
        return result
    except mysql.connector.Error as err:
        print(f"Error reading from database: {err}")
        return None

def execute_write_query(query):
    """Executes INSERT/UPDATE queries"""
    if not ensure_connection():
        return False
    try:
        cursor = conexion.cursor()
        cursor.execute(query)
        conexion.commit()
        cursor.close()
        return True
    except mysql.connector.Error as err:
        print(f"Error writing to database: {err}")
        return False

def log_sensor_error(sensor_name, error_message):
    """Logs sensor errors to the database"""
    error_query = f"""
        INSERT INTO errores 
        (nombre_sensor, id_zona, mensaje_error)
        VALUES ('{sensor_name}', 1, '{error_message}')
    """
    execute_write_query(error_query)

def read_soil_sensor():
    """Reads values from soil sensor with error handling"""
    global soil_sensor
    
    try:
        if soil_sensor is None:
            raise minimalmodbus.SerialException("Sensor not initialized")
            
        # Read soil temperature (register 0x0013)
        temp = soil_sensor.read_register(0x0013) * 0.1  # Convert to proper temperature
        
        # Read soil moisture (register 0x0012)
        moisture = soil_sensor.read_register(0x0012) * 0.1  # Convert to percentage
        
        # Read soil pH (register 0x0006)
        ph = soil_sensor.read_register(0x0006) * 0.01  # Convert to pH value
        
        return temp, moisture, ph
        
    except minimalmodbus.NoResponseError:
        log_sensor_error('Sensor_Suelo_Z1', 
                        'Error de comunicación Modbus - No respuesta del sensor')
        return None, None, None
        
    except minimalmodbus.SerialException:
        log_sensor_error('Sensor_Suelo_Z1', 
                        'Sensor desconectado - Error de puerto serial')
        # Try to reinitialize the sensor
        try:
            soil_sensor = minimalmodbus.Instrument('/dev/ttyUSB0', 1)
            soil_sensor.serial.baudrate = 9600
            soil_sensor.serial.bytesize = 8
            soil_sensor.serial.parity = 'N'
            soil_sensor.serial.stopbits = 1
            soil_sensor.serial.timeout = 1
        except:
            pass
        return None, None, None
        
    except Exception as e:
        log_sensor_error('Sensor_Suelo_Z1', f'Error inesperado: {str(e)}')
        return None, None, None

# Hardware setup
lampara = gpiozero.OutputDevice(27, active_high=False, initial_value=False)
dhtDevice = adafruit_dht.DHT11(board.D4)

try:
    # Initial database connection
    print("Estableciendo conexión inicial con la base de datos...")
    while not ensure_connection():
        print("Retrying initial connection...")
        time.sleep(5)
    print("Conexión establecida exitosamente")

    # Cache for last valid sensor readings
    ultima_temperatura = 25.0
    ultima_humedad = 50.0
    ultima_temperatura_suelo = 25.0
    ultima_humedad_suelo = 50.0
    ultima_ph_suelo = 7.0

    while True:
        try:
            # Get relay state from database
            query_rele = """
                SELECT estado 
                FROM actuador_rele1 
                WHERE id_zona = 1 
                ORDER BY fecha_hora DESC 
                LIMIT 1
            """
            resultado_rele = execute_read_query(query_rele)
            
            # Control lamp based on database state
            if resultado_rele and len(resultado_rele) > 0:
                estado_rele = resultado_rele[0]['estado']
                if estado_rele:
                    print("Encendiendo lámpara según base de datos")
                    lampara.on()
                else:
                    print("Apagando lámpara según base de datos")
                    lampara.off()
            
            # Read DHT11 sensor (air temperature and humidity)
            try:
                temperatura = dhtDevice.temperature
                humedad = dhtDevice.humidity
                
                if temperatura is not None and humedad is not None:
                    ultima_temperatura = temperatura
                    ultima_humedad = humedad
            except:
                print("Error leyendo DHT11, usando últimas lecturas válidas")
                temperatura = ultima_temperatura
                humedad = ultima_humedad
            
            print(f"Temperatura Aire: {temperatura:.1f}°C    Humedad Aire: {humedad:.0f}%")
            
            # Read soil sensor values
            temp_suelo, hum_suelo, ph_suelo = read_soil_sensor()
            
            # Update cached values if readings are valid
            if temp_suelo is not None:
                ultima_temperatura_suelo = temp_suelo
            else:
                temp_suelo = ultima_temperatura_suelo
                
            if hum_suelo is not None:
                ultima_humedad_suelo = hum_suelo
            else:
                hum_suelo = ultima_humedad_suelo
                
            if ph_suelo is not None:
                ultima_ph_suelo = ph_suelo
            else:
                ph_suelo = ultima_ph_suelo
            
            print(f"Suelo - Temp: {temp_suelo:.1f}°C  Humedad: {hum_suelo:.1f}%  pH: {ph_suelo:.2f}")
            
            # Save all sensor readings to database
            current_time = datetime.now()
            
            # Air temperature (DHT11)
            query_temp = f"""
                INSERT INTO sensor_temperatura 
                (nombre, id_zona, fecha_hora, valor) 
                VALUES ('Sensor_Temp_Z1', 1, '{current_time}', {temperatura})
            """
            execute_write_query(query_temp)
            
            # Air humidity (DHT11)
            query_hum = f"""
                INSERT INTO sensor_humedad_aire 
                (nombre, id_zona, fecha_hora, valor) 
                VALUES ('Sensor_Hum_Z1', 1, '{current_time}', {humedad})
            """
            execute_write_query(query_hum)
            
            # Soil temperature
            query_temp_suelo = f"""
                INSERT INTO sensor_temperatura_suelo 
                (nombre, id_zona, fecha_hora, valor) 
                VALUES ('Sensor_Temp_Suelo_Z1', 1, '{current_time}', {temp_suelo})
            """
            execute_write_query(query_temp_suelo)
            
            # Soil humidity
            query_hum_suelo = f"""
                INSERT INTO sensor_humedad_suelo 
                (nombre, id_zona, fecha_hora, valor) 
                VALUES ('Sensor_Hum_Suelo_Z1', 1, '{current_time}', {hum_suelo})
            """
            execute_write_query(query_hum_suelo)
            
            # Soil pH
            query_ph_suelo = f"""
                INSERT INTO sensor_ph_suelo 
                (nombre, id_zona, fecha_hora, valor) 
                VALUES ('Sensor_PH_Suelo_Z1', 1, '{current_time}', {ph_suelo})
            """
            execute_write_query(query_ph_suelo)
            
            # Wait before next reading
            time.sleep(5)
            
        except Exception as e:
            print(f"Error en el bucle principal: {e}")
            log_sensor_error('Sistema', f'Error en bucle principal: {str(e)}')
            time.sleep(5)  # Wait before retrying the main loop
            
except KeyboardInterrupt:
    print("\nPrograma detenido por el usuario")
    lampara.off()  # Turn off lamp before exiting
finally:
    # Cleanup
    if conexion:
        conexion.close()
    lampara.close()  # Release GPIO pin