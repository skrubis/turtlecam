"""Environmental sensor module for TurtleCam.

This module interfaces with the DHT22 temperature-humidity sensor
and provides methods to read current environmental conditions.
"""

import time
import logging
import random
import threading
import time
from datetime import datetime

# Import sensor library with fallback for development on non-Pi systems
try:
    import adafruit_dht
    import board

    DHT_AVAILABLE = True
except (ImportError, NotImplementedError):
    DHT_AVAILABLE = False
    logging.warning("adafruit_dht library not found. Using mock sensor.")

logger = logging.getLogger(__name__)


class DHT22Sensor:
    """Interface to DHT22 temperature-humidity sensor."""
    
    def __init__(self, 
                 data_store,
                 pin=4,            # Default to GPIO4
                 poll_interval=60, # Seconds between readings
                 mock_mode=not DHT_AVAILABLE):
        """Initialize the DHT22 sensor interface.
        
        Args:
            pin (int): GPIO pin number the sensor is connected to
            poll_interval (int): Time between readings in seconds
            db_path (str): Path to SQLite database for logging
            mock_mode (bool): If True, use a mock sensor for testing
        """
        self.data_store = data_store
        self.pin = pin
        self.poll_interval = poll_interval
        self.mock_mode = mock_mode
        
        # Thread control
        self.running = False
        self.lock = threading.RLock()
        
        # Last readings
        self.last_temperature = None
        self.last_humidity = None
        self.last_read_time = None
        self.read_count = 0
        self.error_count = 0
        
        # Initialize sensor
        self._init_sensor()
        
        # Thread for polling
        self.poll_thread = None
        
    def _init_sensor(self):
        """Initialize the DHT22 sensor."""
        if self.mock_mode:
            logger.info("Initializing mock DHT22 sensor")
            self.sensor = None
        else:
            try:
                # Create the DHT22 device using the specified pin
                logger.info(f"Initializing DHT22 sensor on GPIO{self.pin}")
                pin_obj = getattr(board, f"D{self.pin}")
                self.sensor = adafruit_dht.DHT22(pin_obj)
            except Exception as e:
                logger.error(f"Error initializing DHT22: {e}")
                self.sensor = None
                self.mock_mode = True
                
    def start(self):
        """Start the sensor polling thread."""
        with self.lock:
            if self.running:
                logger.warning("DHT22 sensor already running")
                return
                
            self.running = True
            
            # Create and start the polling thread
            self.poll_thread = threading.Thread(target=self._polling_loop)
            self.poll_thread.daemon = True
            self.poll_thread.start()
            
            logger.info("Started DHT22 sensor polling")
            
    def stop(self):
        """Stop the sensor polling thread."""
        with self.lock:
            if not self.running:
                return
                
            self.running = False
            
            # Wait for polling thread to finish
            if self.poll_thread and self.poll_thread.is_alive():
                self.poll_thread.join(timeout=5.0)
                
            logger.info("Stopped DHT22 sensor polling")
            
            # Clean up sensor if needed
            if not self.mock_mode and self.sensor:
                try:
                    self.sensor.exit()
                except:
                    pass
    
    def _polling_loop(self):
        """Main polling loop for the sensor."""
        try:
            while self.running:
                # Read sensor values
                self._read_sensor()
                
                # Sleep until next reading
                time.sleep(self.poll_interval)
                
        except Exception as e:
            logger.error(f"Error in DHT22 polling loop: {e}")
        finally:
            logger.info("DHT22 polling loop ended")
    
    def _read_sensor(self):
        """Read sensor values, validate them, and update state."""
        temp = None
        humidity = None
        timestamp = datetime.now()

        try:
            if self.mock_mode:
                # Generate simple mock data
                temp = 25.0 + random.uniform(-1.0, 1.0)
                humidity = 55.0 + random.uniform(-5.0, 5.0)
                logger.debug(f"Mock DHT22 reading: {temp:.1f}°C, {humidity:.1f}%")
            elif self.sensor:
                # Read from actual sensor
                temp = self.sensor.temperature
                humidity = self.sensor.humidity
                logger.debug(f"DHT22 reading: {temp:.1f}°C, {humidity:.1f}%")

            # Validate readings
            if temp is not None and humidity is not None and (0 <= temp <= 50) and (0 <= humidity <= 100):
                with self.lock:
                    self.last_temperature = temp
                    self.last_humidity = humidity
                    self.last_read_time = timestamp
                    self.read_count += 1
                # Log valid reading to database
                self._log_to_database(temp, humidity, timestamp)
            else:
                logger.warning(f"Invalid sensor reading: temp={temp}, humidity={humidity}")
                self.error_count += 1

        except RuntimeError as e:
            # DHT sensors sometimes fail to read. This is expected.
            logger.warning(f"DHT22 reading failed: {e}")
            self.error_count += 1
            time.sleep(2)  # Wait before retrying
        except Exception as e:
            logger.error("Unexpected error reading DHT22 sensor", exc_info=True)
            self.error_count += 1
    
    def _log_to_database(self, temperature, humidity, timestamp):
        """Log sensor readings to the database via the DataStore."""
        if self.data_store:
            self.data_store.log_env_reading(temperature, humidity, timestamp)
        else:
            logger.warning("DataStore not available, cannot log environmental data.")
    
    def get_temperature(self):
        """Get the last temperature reading.
        
        Returns:
            float: Temperature in Celsius, or None if not available
        """
        with self.lock:
            return self.last_temperature
    
    def get_humidity(self):
        """Get the last humidity reading.
        
        Returns:
            float: Relative humidity in percent, or None if not available
        """
        with self.lock:
            return self.last_humidity
    
    def get_last_reading_time(self):
        """Get the timestamp of the last reading.
        
        Returns:
            datetime: Timestamp of last reading, or None if not available
        """
        with self.lock:
            return self.last_read_time
    
    def force_reading(self):
        """Force an immediate sensor reading.
        
        Returns:
            tuple: (temperature, humidity) or (None, None) on failure
        """
        self._read_sensor()
        return (self.last_temperature, self.last_humidity)
