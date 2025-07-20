"""Relay controller module for TurtleCam.

This module manages relay control for lights, heating elements, and other devices
according to schedules and manual overrides.
"""

import time
import logging
import threading
import schedule
import json
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

# Import GPIO library with fallback for development on non-Pi systems
try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logging.warning("RPi.GPIO not available, using mock GPIO")

logger = logging.getLogger(__name__)


class RelayController:
    """Controls relay board for terrarium management.
    
    Manages scheduled and manual control of devices like lights and heaters.
    """
    
    def __init__(self, 
                 relay_config: dict,
                 data_store, # Add data_store for logging
                 mock_mode: bool = not GPIO_AVAILABLE):
        """Initialize the relay controller.
        
        Args:
            config_path (str): Path to relay configuration YAML
            mock_mode (bool): If True, use mock GPIO for testing
        """
        self.config = relay_config
        self.data_store = data_store
        self.mock_mode = mock_mode
        
        # Thread control
        self.running = False
        self.lock = threading.RLock()
        
        # Relay state tracking
        self.relays = {}  # {name: {"pin": pin, "state": state}}
        self.manual_overrides = {}  # {name: {"state": state, "until": datetime}}
        self.last_schedule_check = None
        
        # Scheduling
        self.scheduler = schedule.Scheduler()
        
        # Initialize GPIO and load configuration
        self._init_gpio()
        self._load_config(relay_config)
        
        # Thread for scheduling
        self.schedule_thread = None
        
    def _init_gpio(self):
        """Initialize GPIO interface."""
        if self.mock_mode:
            logger.info("Using mock GPIO interface")
            return
            
        try:
            # Set up GPIO using BCM numbering
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            logger.info("Initialized GPIO interface")
        except Exception as e:
            logger.error(f"Error initializing GPIO: {e}")
            self.mock_mode = True
        
    def _load_config(self, config: dict):
        """Load relay configuration from a dictionary."""
        try:
            # Process relay definitions
            relays_config = config.get('relays', {})
            for name, relay_config in relays_config.items():
                pin = relay_config.get('pin')
                if pin is None:
                    logger.warning(f"No pin defined for relay '{name}', skipping")
                    continue

                self.relays[name] = {
                    "pin": pin,
                    "state": relay_config.get('initial_state', False),
                    "description": relay_config.get('description', ''),
                    "active_high": relay_config.get('active_high', True)
                }
                self._setup_relay_pin(name)

            # Set up schedules
            schedules_config = config.get('schedules', {})
            for name, schedule_entries in schedules_config.items():
                if name not in self.relays:
                    logger.warning(f"Schedule for unknown relay '{name}', skipping")
                    continue
                
                for entry in schedule_entries:
                    time_spec = entry.get('time')
                    state = entry.get('state')
                    days = entry.get('days', 'all')
                    if time_spec is not None and state is not None:
                        self._add_schedule_entry(name, time_spec, state, days)
                    else:
                        logger.warning(f"Incomplete schedule entry for '{name}': {entry}")

            logger.info("Loaded relay configuration and schedules")
        except Exception as e:
            logger.error("Error loading relay configuration", exc_info=True)
            return False
    
    def _setup_relay_pin(self, relay_name):
        """Set up GPIO pin for a relay.
        
        Args:
            relay_name (str): Name of the relay
        """
        if relay_name not in self.relays:
            logger.error(f"Unknown relay: {relay_name}")
            return
            
        relay = self.relays[relay_name]
        pin = relay["pin"]
        
        if not self.mock_mode:
            try:
                # Set pin as output
                GPIO.setup(pin, GPIO.OUT)
                
                # Set initial state
                self._set_pin_state(pin, relay["state"], relay["active_high"])
                
                logger.debug(f"Set up GPIO{pin} for relay '{relay_name}'")
            except Exception as e:
                logger.error(f"Error setting up GPIO{pin} for relay '{relay_name}': {e}")
    
    def _set_pin_state(self, pin, state, active_high=True):
        """Set physical pin state, taking into account active high/low logic.
        
        Args:
            pin (int): GPIO pin number
            state (bool): Desired logical state (True=on, False=off)
            active_high (bool): Whether relay is active high (True) or active low (False)
        """
        # Calculate physical pin state based on logical state and active mode
        pin_state = state if active_high else not state
        
        if not self.mock_mode:
            try:
                GPIO.output(pin, GPIO.HIGH if pin_state else GPIO.LOW)
            except Exception as e:
                logger.error(f"Error setting GPIO{pin} state: {e}")
        else:
            logger.debug(f"Mock GPIO{pin} set to {'HIGH' if pin_state else 'LOW'}")
    
    def _add_schedule_entry(self, relay_name, time_spec, state, days='all'):
        """Add a schedule entry for a relay.
        
        Args:
            relay_name (str): Name of the relay
            time_spec (str): Time specification in 24-hour format (HH:MM)
            state (bool): State to set (True=on, False=off)
            days (str or list): Days to apply schedule ('all' or list of day names)
        """
        try:
            # Create a job function
            job_func = lambda: self.set_relay(relay_name, state, manual=False)
            
            # Parse the time specification
            if ':' in time_spec:
                hour, minute = time_spec.split(':')
                time_str = f"{hour.zfill(2)}:{minute.zfill(2)}"
                
                # Create the schedule based on days
                if days == 'all' or days == ['all']:
                    self.scheduler.every().day.at(time_str).do(job_func)
                    logger.debug(f"Scheduled {relay_name} {'ON' if state else 'OFF'} at {time_str} every day")
                else:
                    # Handle specific days
                    if isinstance(days, str):
                        days = [days]
                        
                    for day in days:
                        day_attr = getattr(self.scheduler.every(), day.lower(), None)
                        if day_attr:
                            day_attr.at(time_str).do(job_func)
                            logger.debug(f"Scheduled {relay_name} {'ON' if state else 'OFF'} at {time_str} on {day}")
            else:
                logger.warning(f"Invalid time format: {time_spec}")
                
        except Exception as e:
            logger.error(f"Error adding schedule entry: {e}")
    
    def start(self):
        """Start the relay controller."""
        with self.lock:
            if self.running:
                logger.warning("Relay controller already running")
                return
                
            self.running = True
            
            # Create and start the scheduling thread
            self.schedule_thread = threading.Thread(target=self._schedule_loop)
            self.schedule_thread.daemon = True
            self.schedule_thread.start()
            
            logger.info("Started relay controller")
            
    def stop(self):
        """Stop the relay controller."""
        with self.lock:
            if not self.running:
                return
                
            self.running = False
            
            # Wait for scheduling thread to finish
            if self.schedule_thread and self.schedule_thread.is_alive():
                self.schedule_thread.join(timeout=5.0)
                
            logger.info("Stopped relay controller")
            
            # Clean up GPIO if needed
            if not self.mock_mode:
                try:
                    GPIO.cleanup()
                    logger.info("Cleaned up GPIO")
                except:
                    pass
    
    def _schedule_loop(self):
        """Main scheduling loop."""
        try:
            while self.running:
                # Run pending schedule jobs
                self.scheduler.run_pending()
                
                # Check for expired manual overrides
                self._check_manual_overrides()
                
                # Sleep briefly
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"Error in scheduling loop: {e}")
        finally:
            logger.info("Scheduling loop ended")
    
    def _check_manual_overrides(self):
        """Check for and remove expired manual overrides."""
        now = datetime.now()
        expired = []
        
        # Find expired overrides
        for relay_name, override in self.manual_overrides.items():
            if override.get('until') and now >= override['until']:
                expired.append(relay_name)
        
        # Remove expired overrides and restore scheduled state
        for relay_name in expired:
            override = self.manual_overrides.pop(relay_name)
            logger.info(f"Manual override for '{relay_name}' expired")
            
            # We'll let the next scheduler run handle the state
    
    def set_relay(self, relay_name, state, manual=True, duration_minutes=None):
        """Set relay state.
        
        Args:
            relay_name (str): Name of the relay
            state (bool): State to set (True=on, False=off)
            manual (bool): Whether this is a manual change (vs scheduled)
            duration_minutes (int, optional): Duration for manual change
            
        Returns:
            bool: True if successful, False otherwise
        """
        with self.lock:
            relay = self.relays.get(relay_name)
            if not relay:
                logger.error(f"Attempted to set unknown relay '{relay_name}'")
                return False
            
            # Update state
            relay["state"] = state
            self._set_pin_state(relay["pin"], state, relay["active_high"])

            # Log the change to the database
            trigger_type = "manual" if manual else "schedule"
            self.data_store.log_relay_change(relay_name, state, trigger_type)
            
            # Update relay state
            relay["state"] = state
            
            # Handle manual overrides
            if manual:
                if duration_minutes:
                    # Set expiry time for this override
                    expiry = datetime.now() + timedelta(minutes=duration_minutes)
                    self.manual_overrides[relay_name] = {
                        "state": state,
                        "until": expiry
                    }
                    logger.info(f"Manual override: {relay_name} {'ON' if state else 'OFF'} for {duration_minutes} minutes")
                else:
                    # Indefinite manual override
                    self.manual_overrides[relay_name] = {
                        "state": state,
                        "until": None
                    }
                    logger.info(f"Manual override: {relay_name} {'ON' if state else 'OFF'} indefinitely")
            else:
                # This is a scheduled change, remove any manual override
                if relay_name in self.manual_overrides:
                    self.manual_overrides.pop(relay_name)
                
            logger.info(f"Set relay '{relay_name}' to {'ON' if state else 'OFF'}")
            return True
    
    def get_relay_state(self, relay_name):
        """Get the current state of a relay.
        
        Args:
            relay_name (str): Name of the relay
            
        Returns:
            bool or None: Current state (True=on, False=off), or None if unknown
        """
        with self.lock:
            relay = self.relays.get(relay_name)
            return relay["state"] if relay else None
    
    def get_all_states(self):
        """Get current states of all relays.
        
        Returns:
            dict: Dictionary of {relay_name: state}
        """
        with self.lock:
            return {name: relay["state"] for name, relay in self.relays.items()}
    
    def get_relay_info(self, relay_name):
        """Get detailed information about a relay.
        
        Args:
            relay_name (str): Name of the relay
            
        Returns:
            dict or None: Relay information or None if unknown
        """
        with self.lock:
            relay = self.relays.get(relay_name)
            if not relay:
                return None
                
            # Copy information
            info = {
                "name": relay_name,
                "state": relay["state"],
                "pin": relay["pin"],
                "description": relay.get("description", "")
            }
            
            # Add override information if present
            override = self.manual_overrides.get(relay_name)
            if override:
                info["manual_override"] = True
                if override.get("until"):
                    info["override_until"] = override["until"].isoformat()
                else:
                    info["override_until"] = None
            else:
                info["manual_override"] = False
                
            return info
    
    def get_all_info(self):
        """Get detailed information about all relays.
        
        Returns:
            dict: Dictionary of {relay_name: info}
        """
        return {name: self.get_relay_info(name) for name in self.relays}
    
    def handle_high_temperature(self, temperature):
        """Handle high temperature safety action.
        
        This is called by the environmental monitor when temperature
        exceeds safe levels for an extended period.
        
        Args:
            temperature (float): Current temperature
        """
        logger.warning(f"Safety action: Turning off heating due to high temperature ({temperature:.1f}°C)")
        
        # Turn off UV/heat relay if present
        if "uv_heat" in self.relays:
            self.set_relay("uv_heat", False, manual=True, duration_minutes=30)
            
        # Turn on fan if present
        if "fan" in self.relays:
            self.set_relay("fan", True, manual=True, duration_minutes=30)
            

