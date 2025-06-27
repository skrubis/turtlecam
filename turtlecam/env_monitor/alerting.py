"""Environmental alerting module for TurtleCam.

This module monitors environmental conditions and triggers alerts
when temperature or humidity exceed defined thresholds.
"""

import time
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class EnvAlertMonitor:
    """Monitors environmental conditions and triggers alerts."""
    
    def __init__(self, 
                 sensor=None,
                 telegram_sender=None,
                 check_interval=60,
                 temp_low_threshold=22.0,
                 temp_high_threshold=33.0,
                 alert_cooldown_minutes=15):
        """Initialize the environmental alert monitor.
        
        Args:
            sensor: DHT22Sensor instance
            telegram_sender: AsyncTelegramSender instance for alerts
            check_interval (int): Seconds between checks
            temp_low_threshold (float): Low temperature threshold in Celsius
            temp_high_threshold (float): High temperature threshold in Celsius
            alert_cooldown_minutes (int): Minimum minutes between repeated alerts
        """
        self.sensor = sensor
        self.telegram_sender = telegram_sender
        self.check_interval = check_interval
        self.temp_low_threshold = temp_low_threshold
        self.temp_high_threshold = temp_high_threshold
        self.alert_cooldown = timedelta(minutes=alert_cooldown_minutes)
        
        # Thread control
        self.running = False
        self.lock = threading.RLock()
        
        # Alert state tracking
        self.last_low_alert_time = None
        self.last_high_alert_time = None
        self.consecutive_high_temp_readings = 0
        
        # Thread for monitoring
        self.monitor_thread = None
        
        # Callback for safety actions (will be set by relay controller)
        self.high_temp_safety_callback = None
        
    def start(self):
        """Start the environmental monitoring thread."""
        with self.lock:
            if self.running:
                logger.warning("Environmental alert monitor already running")
                return
                
            self.running = True
            
            # Create and start the monitoring thread
            self.monitor_thread = threading.Thread(target=self._monitoring_loop)
            self.monitor_thread.daemon = True
            self.monitor_thread.start()
            
            logger.info("Started environmental alert monitoring")
            
    def stop(self):
        """Stop the environmental monitoring thread."""
        with self.lock:
            if not self.running:
                return
                
            self.running = False
            
            # Wait for monitoring thread to finish
            if self.monitor_thread and self.monitor_thread.is_alive():
                self.monitor_thread.join(timeout=5.0)
                
            logger.info("Stopped environmental alert monitoring")
    
    def _monitoring_loop(self):
        """Main monitoring loop."""
        try:
            while self.running:
                # Check environmental conditions
                self._check_conditions()
                
                # Sleep until next check
                time.sleep(self.check_interval)
                
        except Exception as e:
            logger.error(f"Error in environmental monitoring loop: {e}")
        finally:
            logger.info("Environmental monitoring loop ended")
    
    def _check_conditions(self):
        """Check environmental conditions and trigger alerts if needed."""
        if not self.sensor:
            logger.warning("No sensor available for environmental monitoring")
            return
            
        # Get current readings
        temperature = self.sensor.get_temperature()
        
        if temperature is None:
            logger.warning("No temperature reading available")
            return
            
        # Check temperature thresholds
        now = datetime.now()
        
        # Check for low temperature
        if temperature < self.temp_low_threshold:
            # Check if cooldown period has passed since last alert
            if (self.last_low_alert_time is None or 
                    now - self.last_low_alert_time > self.alert_cooldown):
                logger.warning(f"Low temperature alert: {temperature:.1f}°C")
                self._trigger_low_temp_alert(temperature)
                self.last_low_alert_time = now
                
            # Reset high temperature counter
            self.consecutive_high_temp_readings = 0
                
        # Check for high temperature
        elif temperature > self.temp_high_threshold:
            # Increment consecutive high readings counter
            self.consecutive_high_temp_readings += 1
            
            # Check if cooldown period has passed since last alert
            if (self.last_high_alert_time is None or 
                    now - self.last_high_alert_time > self.alert_cooldown):
                logger.warning(f"High temperature alert: {temperature:.1f}°C")
                self._trigger_high_temp_alert(temperature)
                self.last_high_alert_time = now
            
            # Check for safety action threshold (high temp for over 5 minutes)
            # Assuming check_interval is in seconds, we need consecutive readings
            readings_for_5min = int(5 * 60 / self.check_interval)
            if self.consecutive_high_temp_readings >= readings_for_5min:
                logger.error(f"CRITICAL: High temperature for >5 minutes: {temperature:.1f}°C")
                self._trigger_high_temp_safety(temperature)
                # Reset counter after safety action
                self.consecutive_high_temp_readings = 0
                
        else:
            # Temperature is within normal range
            self.consecutive_high_temp_readings = 0
    
    def _trigger_low_temp_alert(self, temperature):
        """Trigger a low temperature alert.
        
        Args:
            temperature (float): Current temperature
        """
        try:
            # Send alert via Telegram if available
            if self.telegram_sender:
                self.telegram_sender.send_temperature_alert(temperature, "low")
                
        except Exception as e:
            logger.error(f"Error sending low temperature alert: {e}")
    
    def _trigger_high_temp_alert(self, temperature):
        """Trigger a high temperature alert.
        
        Args:
            temperature (float): Current temperature
        """
        try:
            # Send alert via Telegram if available
            if self.telegram_sender:
                self.telegram_sender.send_temperature_alert(temperature, "high")
                
        except Exception as e:
            logger.error(f"Error sending high temperature alert: {e}")
    
    def _trigger_high_temp_safety(self, temperature):
        """Trigger safety actions for prolonged high temperature.
        
        This could include turning off heating elements, activating fans, etc.
        
        Args:
            temperature (float): Current temperature
        """
        try:
            # Call safety callback if set
            if self.high_temp_safety_callback:
                logger.info("Triggering high temperature safety action")
                self.high_temp_safety_callback(temperature)
                
            # Also send an alert
            if self.telegram_sender:
                message = (
                    "🚨 *CRITICAL TEMPERATURE ALERT* 🚨\n\n"
                    f"Temperature has been above {self.temp_high_threshold}°C for over 5 minutes!\n"
                    f"Current temperature: *{temperature:.1f}°C*\n\n"
                    "Safety measures have been activated."
                )
                self.telegram_sender.send_message(message, parse_mode="Markdown")
                
        except Exception as e:
            logger.error(f"Error in high temperature safety action: {e}")
    
    def register_safety_callback(self, callback):
        """Register a callback for high temperature safety actions.
        
        Args:
            callback (callable): Function that takes temperature as argument
        """
        self.high_temp_safety_callback = callback
        
    def update_thresholds(self, low=None, high=None):
        """Update temperature threshold values.
        
        Args:
            low (float, optional): New low temperature threshold
            high (float, optional): New high temperature threshold
        """
        with self.lock:
            if low is not None:
                self.temp_low_threshold = low
                logger.info(f"Updated low temperature threshold to {low}°C")
                
            if high is not None:
                self.temp_high_threshold = high
                logger.info(f"Updated high temperature threshold to {high}°C")
