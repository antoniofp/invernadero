import time
import board
import adafruit_dht
import gpiozero
import mysql.connector
from datetime import datetime

db_config = {
   'host': 'localhost',
   'user': 'admin',
   'password': 'admin',  
   'database': 'INVERNADERO'  # Nombre de la base de datos del invernadero
}

def conectar_base_datos():
   try:
       conexion = mysql.connector.connect(**db_config)
       return conexion
   except mysql.connector.Error as err:
       print(f"Error conectando a la base de datos: {err}")
       return None

def obtener_estado_rele():
   """
   Obtiene el estado más reciente del relé 1 de la base de datos
   Retorna: True si está encendido, False si está apagado, None si hay error
   """
   try:
       conexion = conectar_base_datos()
       if conexion is None:
           return None
       
       cursor = conexion.cursor(dictionary=True)
       
       # Consulta para obtener el último estado del relé en la zona 1
       consulta = """
           SELECT estado 
           FROM actuador_rele1 
           WHERE id_zona = 1 
           ORDER BY fecha_hora DESC 
           LIMIT 1
       """
       cursor.execute(consulta)
       
       resultado = cursor.fetchone()
       if resultado:
           return resultado['estado']  # Retorna True si está encendido, False si apagado
       return None
       
   except mysql.connector.Error as err:
       print(f"Error obteniendo estado del relé: {err}")
       return None
   finally:
       # Siempre cerrar conexiones para liberar recursos
       if conexion and conexion.is_connected():
           cursor.close()
           conexion.close()

def guardar_datos_sensores(temperatura, humedad):
   """
   Guarda las lecturas de temperatura y humedad en la base de datos
   Parámetros:
       temperatura: valor de temperatura en Celsius
       humedad: valor de humedad relativa en porcentaje
   """
   try:
       conexion = conectar_base_datos()
       if conexion is None:
           return
       
       cursor = conexion.cursor()
       
       # Guardar lectura de temperatura
       consulta_temp = """
           INSERT INTO sensor_temperatura 
           (nombre, id_zona, fecha_hora, valor) 
           VALUES (%s, %s, %s, %s)
       """
       cursor.execute(consulta_temp, ('Sensor_Temp_Z1', 1, datetime.now(), temperatura))
       
       # Guardar lectura de humedad
       consulta_hum = """
           INSERT INTO sensor_humedad_aire 
           (nombre, id_zona, fecha_hora, valor) 
           VALUES (%s, %s, %s, %s)
       """
       cursor.execute(consulta_hum, ('Sensor_Hum_Z1', 1, datetime.now(), humedad))
       
       # Confirmar los cambios en la base de datos
       conexion.commit()
       
   except mysql.connector.Error as err:
       print(f"Error guardando datos de sensores: {err}")
   finally:
       if conexion and conexion.is_connected():
           cursor.close()
           conexion.close()


lampara = gpiozero.OutputDevice(27, active_high=False, initial_value=False)

dhtDevice = adafruit_dht.DHT11(board.D4)


ultima_temperatura = 25.0
ultima_humedad = 50.0

def leer_temperatura_humedad():

   global ultima_temperatura, ultima_humedad
   try:
       temperatura = dhtDevice.temperature
       humedad = dhtDevice.humidity
       if temperatura is not None and humedad is not None:
           ultima_temperatura = temperatura
           ultima_humedad = humedad
       return temperatura, humedad
   except:
       print("Error leyendo sensor, usando últimas lecturas válidas")
       return ultima_temperatura, ultima_humedad

try:
   while True:
       try:
           # Leer estado del relé de la base de datos y controlar lámpara
           estado_rele = obtener_estado_rele()
           if estado_rele is not None:
               if estado_rele:
                   print("Encendiendo lámpara según base de datos")
                   lampara.on()  # Enciende la lámpara
               else:
                   print("Apagando lámpara según base de datos")
                   lampara.off()  # Apaga la lámpara
           
           # Leer sensores y guardar datos
           temperatura, humedad = leer_temperatura_humedad()
           print(f"Temperatura: {temperatura:.1f}°C    Humedad: {humedad:.0f}%")
           
           # Guardar lecturas en la base de datos
           guardar_datos_sensores(temperatura, humedad)
           
           # Esperar 10 segundos antes de la siguiente lectura
           time.sleep(1)
           
       except Exception as e:
           print(f"Ocurrió un error en el bucle principal: {e}")
           time.sleep(10)  # Esperar antes de reintentar
           
except KeyboardInterrupt:
   print("\nPrograma detenido por el usuario")
   lampara.off()  # Apagar lámpara antes de salir
finally:
   # Limpieza final
   lampara.close()  # Liberar el pin GPIO