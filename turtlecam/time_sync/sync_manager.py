"""Time synchronization manager for TurtleCam.

This module manages system time synchronization using a combination of
NTP and a hardware RTC module (DS3231).
"""

import os
import time
import logging
import threading
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import socket

# Try to import RTC module with fallback
try:
    import board
    import adafruit_ds3231
    import busio
    RTC_AVAILABLE = True
except (ImportError, NotImplementedError):
    RTC_AVAILABLE = False
    logging.warning("RTC module not available, using system time only")

logger = logging.getLogger(__name__)


class TimeSync:
    """Manages time synchronization for TurtleCam."""
    
    def __init__(self, 
                 use_rtc=True,
                 rtc_module="DS3231",
                 ntp_server="pool.ntp.org",
                 sync_interval_hours=24,
                 mock_mode=not RTC_AVAILABLE):
        """Initialize the time synchronization manager.
        
        Args:
            use_rtc (bool): Whether to use RTC module
            rtc_module (str): RTC module type ('DS3231')
            ntp_server (str): NTP server to use
            sync_interval_hours (int): Hours between sync attempts
            mock_mode (bool): Run in mock mode without hardware
        """
        self.use_rtc = use_rtc and not mock_mode
        self.rtc_module = rtc_module
        self.ntp_server = ntp_server
        self.sync_interval = sync_interval_hours * 3600  # Convert to seconds
        self.mock_mode = mock_mode
        
        # RTC device
        self.rtc = None
        
        # Thread control
        self.running = False
        self.lock = threading.RLock()
        
        # Stats
        self.last_ntp_sync = None
        self.last_rtc_sync = None
        self.ntp_sync_count = 0
        self.ntp_sync_failures = 0
        self.rtc_sync_count = 0
        
        # Initialize RTC if available
        if self.use_rtc:
            self._init_rtc()
        
        # Thread for sync
        self.sync_thread = None
        
    def _init_rtc(self):
        """Initialize connection to RTC module."""
        try:
            if self.mock_mode:
                logger.info(f"Mock mode: Simulating {self.rtc_module} RTC")
                return
                
            if self.rtc_module == "DS3231":
                # Initialize I2C
                i2c = busio.I2C(board.SCL, board.SDA)
                
                # Initialize DS3231
                self.rtc = adafruit_ds3231.DS3231(i2c)
                logger.info("Initialized DS3231 RTC module")
            else:
                logger.warning(f"Unknown RTC module: {self.rtc_module}")
                self.use_rtc = False
                
        except Exception as e:
            logger.error(f"Error initializing RTC: {e}")
            self.use_rtc = False
    
    def start(self):
        """Start the time synchronization service."""
        with self.lock:
            if self.running:
                logger.warning("Time sync already running")
                return
                
            self.running = True
            
            # Create and start the sync thread
            self.sync_thread = threading.Thread(target=self._sync_loop)
            self.sync_thread.daemon = True
            self.sync_thread.start()
            
            logger.info("Started time synchronization service")
            
    def stop(self):
        """Stop the time synchronization service."""
        with self.lock:
            if not self.running:
                return
                
            self.running = False
            
            # Wait for sync thread to finish
            if self.sync_thread and self.sync_thread.is_alive():
                self.sync_thread.join(timeout=5.0)
                
            logger.info("Stopped time synchronization service")
    
    def _sync_loop(self):
        """Main synchronization loop."""
        try:
            # Perform initial sync on startup
            self._perform_sync()
            
            while self.running:
                # Sleep until next sync time
                time.sleep(60)  # Check every minute
                
                # Check if it's time for sync
                now = time.time()
                if self.last_ntp_sync is None or now - self.last_ntp_sync > self.sync_interval:
                    self._perform_sync()
                
        except Exception as e:
            logger.error(f"Error in time sync loop: {e}")
        finally:
            logger.info("Time sync loop ended")
    
    def _perform_sync(self):
        """Perform a time synchronization."""
        try:
            ntp_success = self._sync_with_ntp()
            
            if ntp_success:
                # If NTP succeeded, sync RTC from system
                if self.use_rtc:
                    self._sync_rtc_from_system()
            else:
                # If NTP failed, try to get time from RTC
                if self.use_rtc:
                    self._sync_system_from_rtc()
                
        except Exception as e:
            logger.error(f"Error during time sync: {e}")
    
    def _sync_with_ntp(self):
        """Synchronize system time with NTP.
        
        Returns:
            bool: True if successful
        """
        try:
            if self.mock_mode:
                # In mock mode, just simulate a successful sync
                logger.info(f"Mock NTP sync with {self.ntp_server}")
                self.last_ntp_sync = time.time()
                self.ntp_sync_count += 1
                return True
                
            # Check internet connectivity
            if not self._check_connectivity():
                logger.warning("No internet connection, skipping NTP sync")
                self.ntp_sync_failures += 1
                return False
            
            # Use chronyc or ntpdate to sync
            if self._is_tool_available('chronyc'):
                # Try using chrony
                result = subprocess.run(
                    ['sudo', 'chronyc', 'makestep'],
                    capture_output=True, text=True, check=False
                )
                success = result.returncode == 0
            elif self._is_tool_available('ntpdate'):
                # Fall back to ntpdate
                result = subprocess.run(
                    ['sudo', 'ntpdate', self.ntp_server],
                    capture_output=True, text=True, check=False
                )
                success = result.returncode == 0
            else:
                # Last resort: use timedatectl
                result = subprocess.run(
                    ['sudo', 'timedatectl', 'set-ntp', 'true'],
                    capture_output=True, text=True, check=False
                )
                success = result.returncode == 0
                
            if success:
                logger.info("Successfully synchronized system time with NTP")
                self.last_ntp_sync = time.time()
                self.ntp_sync_count += 1
                return True
            else:
                logger.error(f"NTP sync failed: {result.stderr}")
                self.ntp_sync_failures += 1
                return False
                
        except Exception as e:
            logger.error(f"Error during NTP sync: {e}")
            self.ntp_sync_failures += 1
            return False
    
    def _check_connectivity(self):
        """Check internet connectivity.
        
        Returns:
            bool: True if internet is available
        """
        try:
            # Try to connect to Google DNS
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False
    
    def _is_tool_available(self, name):
        """Check if a command-line tool is available.
        
        Args:
            name (str): Command name
            
        Returns:
            bool: True if tool is available
        """
        try:
            devnull = open(os.devnull)
            subprocess.Popen([name], stdout=devnull, stderr=devnull).communicate()
        except OSError:
            return False
        return True
    
    def _sync_rtc_from_system(self):
        """Synchronize RTC from system time."""
        try:
            if not self.use_rtc or not self.rtc:
                return False
                
            if self.mock_mode:
                logger.info("Mock RTC: Synchronized from system time")
                self.last_rtc_sync = time.time()
                self.rtc_sync_count += 1
                return True
                
            # Get current system time
            now = datetime.now()
            
            # Set RTC time
            self.rtc.datetime = now
            
            logger.info(f"Updated RTC from system time: {now}")
            self.last_rtc_sync = time.time()
            self.rtc_sync_count += 1
            return True
            
        except Exception as e:
            logger.error(f"Error syncing RTC from system: {e}")
            return False
    
    def _sync_system_from_rtc(self):
        """Synchronize system time from RTC.
        
        Returns:
            bool: True if successful
        """
        try:
            if not self.use_rtc or not self.rtc:
                return False
                
            if self.mock_mode:
                logger.info("Mock RTC: System time would be synchronized from RTC")
                return True
                
            # Get time from RTC
            rtc_time = self.rtc.datetime
            
            # Format for date command
            time_str = rtc_time.strftime("%Y-%m-%d %H:%M:%S")
            
            # Set system time
            result = subprocess.run(
                ['sudo', 'date', '-s', time_str],
                capture_output=True, text=True, check=False
            )
            
            if result.returncode == 0:
                logger.info(f"Set system time from RTC: {time_str}")
                return True
            else:
                logger.error(f"Failed to set system time from RTC: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Error syncing system from RTC: {e}")
            return False
    
    def get_status(self):
        """Get the current time sync status.
        
        Returns:
            dict: Status information
        """
        with self.lock:
            return {
                "running": self.running,
                "ntp_server": self.ntp_server,
                "rtc_enabled": self.use_rtc,
                "rtc_module": self.rtc_module,
                "last_ntp_sync": self.last_ntp_sync,
                "last_rtc_sync": self.last_rtc_sync,
                "ntp_sync_count": self.ntp_sync_count,
                "ntp_sync_failures": self.ntp_sync_failures,
                "rtc_sync_count": self.rtc_sync_count,
                "current_time": datetime.now().isoformat()
            }
