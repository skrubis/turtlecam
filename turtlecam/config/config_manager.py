"""Configuration manager for TurtleCam.

This module handles loading, saving and validating YAML configuration files.
It provides a centralized way to access configuration values across the system.
"""

import os
import logging
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Union

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages TurtleCam configuration via YAML files."""
    
    # Configuration defaults
    DEFAULT_CONFIG = {
        "system": {
            "base_path": "data",
            "log_level": "INFO",
            "testing_mode": False,
            "max_disk_usage_pct": 85.0
        },
        "camera": {
            "mock_mode": False,
            "preview_width": 640,
            "preview_height": 480,
            "preview_fps": 10,
            "still_width": 3840,
            "still_height": 2160,
            "still_quality": 90,
            "use_picamera2": True
        },
        "motion": {
            "sensitivity": 25,
            "min_area": 500,
            "blur_size": 21,
            "dilate_iterations": 10,
            "history_frames": 50,
            "inactivity_timeout_sec": 10.0,
            "max_gif_frames": 20,
            "gif_fps": 4,
            "max_gif_width": 1920
        },
        "environment": {
            "sensor_pin": 4,
            "poll_interval_sec": 60,
            "temp_low_threshold": 22.0,
            "temp_high_threshold": 33.0,
            "alert_cooldown_min": 15
        },
        "relay": {
            "config_path": "config/relay.yaml",
            "mock_mode": False
        },
        "telegram": {
            "token_file": ".env",
            "admin_chat_ids": []
        },
        "storage": {
            "db_filename": "turtlecam.db",
            "image_dir": "images",
            "archive_dir": "archive",
            "retention_days": 30,
            "auto_cleanup": True
        },
        "time_sync": {
            "use_rtc": True,
            "rtc_module": "DS3231",
            "ntp_server": "pool.ntp.org",
            "sync_interval_hours": 24
        }
    }
    
    def __init__(self, config_path: str = "config/turtlecam.yaml"):
        """Initialize the configuration manager.
        
        Args:
            config_path (str): Path to main configuration file
        """
        self.config_path = Path(config_path)
        self.config = {}
        
        # Load configuration
        self._load_config()
        
    def _load_config(self):
        """Load configuration from file, creating default if needed."""
        try:
            # Check if config file exists
            if not self.config_path.exists():
                # Create parent directories if needed
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Create default configuration
                self.config = self.DEFAULT_CONFIG.copy()
                self._save_config()
                logger.info(f"Created default configuration at {self.config_path}")
            else:
                # Load existing configuration
                with open(self.config_path, 'r') as f:
                    loaded_config = yaml.safe_load(f)
                    
                if not loaded_config:
                    loaded_config = {}
                    
                # Merge with defaults to ensure all required values exist
                self.config = self._merge_configs(self.DEFAULT_CONFIG, loaded_config)
                logger.info(f"Loaded configuration from {self.config_path}")
                
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            # Fallback to defaults
            self.config = self.DEFAULT_CONFIG.copy()
    
    def _save_config(self):
        """Save current configuration to file."""
        try:
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write configuration
            with open(self.config_path, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False)
                
            logger.info(f"Saved configuration to {self.config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return False
    
    def _merge_configs(self, default, override):
        """Recursively merge two configuration dictionaries.
        
        Args:
            default (dict): Default configuration
            override (dict): Override configuration
            
        Returns:
            dict: Merged configuration
        """
        result = default.copy()
        
        for key, value in override.items():
            # If both values are dictionaries, recursively merge
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                # Otherwise override with new value
                result[key] = value
                
        return result
    
    def get(self, path: str, default: Any = None) -> Any:
        """Get configuration value by dot notation path.
        
        Args:
            path (str): Configuration path (e.g., 'system.log_level')
            default (Any, optional): Default value if path not found
            
        Returns:
            Any: Configuration value or default
        """
        try:
            # Split path into components
            components = path.split('.')
            value = self.config
            
            # Navigate through config hierarchy
            for component in components:
                value = value[component]
                
            return value
            
        except (KeyError, TypeError):
            return default
    
    def set(self, path: str, value: Any) -> bool:
        """Set configuration value by dot notation path.
        
        Args:
            path (str): Configuration path (e.g., 'system.log_level')
            value (Any): Value to set
            
        Returns:
            bool: True if successful
        """
        try:
            # Split path into components
            components = path.split('.')
            
            # Navigate to the parent of the target node
            target = self.config
            for component in components[:-1]:
                # Create dict if needed
                if component not in target:
                    target[component] = {}
                target = target[component]
            
            # Set the value
            target[components[-1]] = value
            
            return True
            
        except Exception as e:
            logger.error(f"Error setting config value at {path}: {e}")
            return False
    
    def save(self) -> bool:
        """Save current configuration.
        
        Returns:
            bool: True if successful
        """
        return self._save_config()
    
    def reload(self) -> bool:
        """Reload configuration from file.
        
        Returns:
            bool: True if successful
        """
        try:
            self._load_config()
            return True
        except Exception as e:
            logger.error(f"Error reloading configuration: {e}")
            return False
    
    def get_section(self, section: str) -> Dict[str, Any]:
        """Get an entire configuration section.
        
        Args:
            section (str): Section name
            
        Returns:
            dict: Configuration section or empty dict
        """
        try:
            return self.config[section].copy()
        except KeyError:
            return {}
    
    def update_section(self, section: str, values: Dict[str, Any]) -> bool:
        """Update an entire configuration section.
        
        Args:
            section (str): Section name
            values (dict): Values to update
            
        Returns:
            bool: True if successful
        """
        try:
            # Create section if it doesn't exist
            if section not in self.config:
                self.config[section] = {}
                
            # Update values
            self.config[section].update(values)
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating config section {section}: {e}")
            return False
    
    def get_all(self) -> Dict[str, Any]:
        """Get entire configuration.
        
        Returns:
            dict: Complete configuration
        """
        return self.config.copy()
    
    @staticmethod
    def set_log_level(level_name):
        """Set the logging level.
        
        Args:
            level_name (str): Level name (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            
        Returns:
            bool: True if successful
        """
        try:
            # Get the numeric level
            level = getattr(logging, level_name.upper())
            
            # Set the root logger level
            logging.getLogger().setLevel(level)
            
            logger.info(f"Set log level to {level_name}")
            return True
            
        except (AttributeError, TypeError):
            logger.error(f"Invalid log level: {level_name}")
            return False
