"""Environmental sensor module for TurtleCam.

This module interfaces with the DHT22 temperature-humidity sensor
and provides methods to read current environmental conditions.
"""

import time
import logging
import threading
import sqlite3
from datetime import datetime
from pathlib import Path

# Import sensor library with fallback for development on non-Pi systems
try:
    import adafruit_dht
    import board
    DHT_AVAILABLE = True
except (ImportError, NotImplementedError):
    DHT_AVAILABLE = False
    logging.warning("adafruit_dht not available, using mock sensor")

logger = logging.getLogger(__name__)


class DHT22Sensor:
    """Interface to DHT22 temperature-humidity sensor."""
    
    def __init__(self, 
                 pin=4,            # Default to GPIO4
                 poll_interval=60, # Seconds between readings
                 db_path="data/turtlecam.db",
                 mock_mode=not DHT_AVAILABLE):
        """Initialize the DHT22 sensor interface.
        
        Args:
            pin (int): GPIO pin number the sensor is connected to
            poll_interval (int): Time between readings in seconds
            db_path (str): Path to SQLite database for logging
            mock_mode (bool): If True, use a mock sensor for testing
        """
        self.pin = pin
        self.poll_interval = poll_interval
        self.db_path = Path(db_path)
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
        
        # Initialize sensor and database
        self._init_sensor()
        self._init_database()
        
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
                
    def _init_database(self):
        """Initialize the SQLite database for logging."""
        try:
            # Ensure the directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Connect and create table if needed
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create env_log table if not exists
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS env_log (
                ts            DATETIME PRIMARY KEY,
                temp_c        REAL,
                humidity_pct  REAL
            )
            ''')
            
            conn.commit()
            conn.close()
            logger.info(f"Initialized database at {self.db_path}")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
        
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
                
                # Log to database if successful
                if self.last_temperature is not None and self.last_humidity is not None:
                    self._log_to_database(
                        self.last_temperature, self.last_humidity, self.last_read_time
                    )
                
                # Sleep until next reading
                time.sleep(self.poll_interval)
                
        except Exception as e:
            logger.error(f"Error in DHT22 polling loop: {e}")
        finally:
            logger.info("DHT22 polling loop ended")
    
    def _read_sensor(self):
        """Read sensor values and update state."""
        try:
            if self.mock_mode:
                # Generate mock values with some drift
                import random
                import math
                
                # Create a daily cycle with some noise
                t = time.time() / 3600  # Convert to hours
                daily_cycle = math.sin(t * 2 * math.pi / 24)  # 24-hour cycle
                
                # Temperature ranges from 22-33°C with daily cycle and noise
                temp_base = 27.5  # Center point
                temp_amplitude = 5.0  # Daily range
                temp_noise = 0.5  # Random fluctuation
                temp = temp_base + daily_cycle * temp_amplitude + (random.random() - 0.5) * temp_noise
                
                # Humidity ranges from 40-70% with inverse relationship to temp
                humidity_base = 55.0  # Center point
                humidity_amplitude = 15.0  # Daily range
                humidity_noise = 2.0  # Random fluctuation
                humidity = humidity_base - daily_cycle * humidity_amplitude + (random.random() - 0.5) * humidity_noise
                
                # Clamp values to reasonable ranges
                temp = max(21.0, min(35.0, temp))
                humidity = max(35.0, min(75.0, humidity))
                
                timestamp = datetime.now()
                
                with self.lock:
                    self.last_temperature = temp
                    self.last_humidity = humidity
                    self.last_read_time = timestamp
                    self.read_count += 1
                    
                logger.debug(f"Mock DHT22 reading: {temp:.1f}°C, {humidity:.1f}%")
                
            else:
                # Read from actual sensor
                try:
                    # Try to read values - DHT sensors can be flaky
                    # and sometimes need multiple attempts
                    temp = self.sensor.temperature
                    humidity = self.sensor.humidity
                    timestamp = datetime.now()
                    
                    with self.lock:
                        self.last_temperature = temp
                        self.last_humidity = humidity
                        self.last_read_time = timestamp
                        self.read_count += 1
                        
                    logger.debug(f"DHT22 reading: {temp:.1f}°C, {humidity:.1f}%")
                    
                except RuntimeError as e:
                    # DHT sensors sometimes fail to read
                    logger.warning(f"DHT22 reading failed: {e}")
                    self.error_count += 1
                    time.sleep(2)  # Wait before retrying
                    
        except Exception as e:
            logger.error(f"Error reading DHT22: {e}")
            self.error_count += 1
    
    def _log_to_database(self, temperature, humidity, timestamp=None):
        """Log sensor readings to database.
        
        Args:
            temperature (float): Temperature in Celsius
            humidity (float): Relative humidity in percent
            timestamp (datetime, optional): Reading timestamp, defaults to now
        """
        if timestamp is None:
            timestamp = datetime.now()
            
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Insert record
            cursor.execute('''
            INSERT INTO env_log (ts, temp_c, humidity_pct)
            VALUES (?, ?, ?)
            ''', (
                timestamp.isoformat(), temperature, humidity
            ))
            
            conn.commit()
            conn.close()
            
            logger.debug(f"Logged environmental data to database: {temperature:.1f}°C, {humidity:.1f}%")
            
        except Exception as e:
            logger.error(f"Error logging to database: {e}")
    
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
