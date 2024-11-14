import time
import board
import adafruit_dht
import gpiozero
import mysql.connector
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

def ensure_connection():
    """Ensures database connection is active, reconnects if needed"""
    global conexion
    try:
        # Check if connection doesn't exist or is not active
        if conexion is None or not conexion.is_connected():
            print("Database connection lost. Attempting to reconnect...")
            try:
                conexion = mysql.connector.connect(**db_config)
                print("Successfully reconnected to database")
            except mysql.connector.Error as err:
                print(f"Failed to reconnect: {err}")
                # Wait before allowing another reconnection attempt
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

# Hardware setup - GPIO 27 for lamp control
lampara = gpiozero.OutputDevice(27, active_high=False, initial_value=False)
# DHT11 sensor setup on GPIO 4
dhtDevice = adafruit_dht.DHT11(board.D4)

try:
    # Initial database connection
    print("Estableciendo conexión inicial con la base de datos...")
    while not ensure_connection():  # Keep trying until we get a connection
        print("Retrying initial connection...")
        time.sleep(5)
    print("Conexión establecida exitosamente")

    # Cache for last valid sensor readings
    ultima_temperatura = 25.0
    ultima_humedad = 50.0

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
            
            # Read temperature and humidity from sensor
            try:
                temperatura = dhtDevice.temperature
                humedad = dhtDevice.humidity
                
                # Update cache if reading is valid
                if temperatura is not None and humedad is not None:
                    ultima_temperatura = temperatura
                    ultima_humedad = humedad
            except:
                print("Error leyendo sensor, usando últimas lecturas válidas")
                temperatura = ultima_temperatura
                humedad = ultima_humedad
            
            print(f"Temperatura: {temperatura:.1f}°C    Humedad: {humedad:.0f}%")
            
            # Save temperature reading
            query_temp = f"""
                INSERT INTO sensor_temperatura 
                (nombre, id_zona, fecha_hora, valor) 
                VALUES ('Sensor_Temp_Z1', 1, '{datetime.now()}', {temperatura})
            """
            execute_write_query(query_temp)
            
            # Save humidity reading
            query_hum = f"""
                INSERT INTO sensor_humedad_aire 
                (nombre, id_zona, fecha_hora, valor) 
                VALUES ('Sensor_Hum_Z1', 1, '{datetime.now()}', {humedad})
            """
            execute_write_query(query_hum)
            
            time.sleep(1)
            
        except Exception as e:
            print(f"Error en el bucle principal: {e}")
            time.sleep(10)  # Wait before retrying the main loop
            
except KeyboardInterrupt:
    print("\nPrograma detenido por el usuario")
    lampara.off()  # Turn off lamp before exiting
finally:
    # Cleanup
    if conexion:
        conexion.close()
    lampara.close()  # Release GPIO pin