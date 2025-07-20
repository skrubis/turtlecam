"""Main module for TurtleCam.

This is the entry point for the TurtleCam application, coordinating all components
including vision pipeline, environmental monitoring, relay control, and Telegram bot.
"""

import os
import sys
import time
import logging
import argparse
import threading
from pathlib import Path
from datetime import datetime
import signal
from dotenv import load_dotenv

# Import TurtleCam modules
from turtlecam.config.config_manager import ConfigManager
from turtlecam.vision.orchestrator import VisionOrchestrator
from turtlecam.env_monitor.sensor import DHT22Sensor
from turtlecam.env_monitor.alerting import EnvAlertMonitor
from turtlecam.relay.controller import RelayController
from turtlecam.storage.data_store import DataStore
from turtlecam.telegram.bot import TurtleBot, AsyncTelegramSender

# Set up logger
logger = logging.getLogger(__name__)


class TurtleCam:
    """Main TurtleCam application class."""
    
    def __init__(self, config_path=None):
        """Initialize the TurtleCam application.
        
        Args:
            config_path (str, optional): Path to configuration file
        """
        # Set up signal handling
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Initialize components
        self.running = False
        self.config = None
        self.data_store = None
        self.vision = None
        self.sensor = None
        self.alert_monitor = None
        self.relay = None
        self.telegram_bot = None
        self.telegram_sender = None
        
        # Set up configuration
        self._init_config(config_path)
        
        # Set up logging
        self._init_logging()
        
    def _init_config(self, config_path):
        """Initialize configuration.
        
        Args:
            config_path (str, optional): Path to configuration file
        """
        try:
            # Use specified config path or default
            if not config_path:
                config_path = "config/turtlecam.yaml"
                
            self.config = ConfigManager(config_path)
            logger.info(f"Loaded configuration from {config_path}")
            
        except Exception as e:
            logger.error(f"Error initializing configuration: {e}")
            sys.exit(1)
    
    def _init_logging(self):
        """Initialize logging system."""
        try:
            # Configure root logger
            log_level = self.config.get("system.log_level", "INFO")
            ConfigManager.set_log_level(log_level)
            
            # Set up log file handler if needed
            log_file = self.config.get("system.log_file")
            if log_file:
                log_path = Path(log_file)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                
                file_handler = logging.FileHandler(log_file)
                file_handler.setFormatter(logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                ))
                logging.getLogger().addHandler(file_handler)
                
            logger.info(f"Logging initialized at level {log_level}")
            
        except Exception as e:
            logger.error(f"Error setting up logging: {e}")
    
    def _signal_handler(self, sig, frame):
        """Handle termination signals.
        
        Args:
            sig: Signal number
            frame: Current stack frame
        """
        logger.info(f"Received signal {sig}, shutting down")
        self.stop()
    
    def start(self):
        """Start the TurtleCam application."""
        if self.running:
            logger.warning("TurtleCam is already running")
            return
            
        logger.info("Starting TurtleCam")
        self.running = True
        
        try:
            # Initialize data store
            data_path = self.config.get("system.base_path", "data")
            db_filename = self.config.get("storage.db_filename", "turtlecam.db")
            image_dir = self.config.get("storage.image_dir", "images")
            archive_dir = self.config.get("storage.archive_dir", "archive")
            max_disk_usage = self.config.get("system.max_disk_usage_pct", 85.0)
            auto_cleanup = self.config.get("storage.auto_cleanup", True)
            
            self.data_store = DataStore(
                base_path=data_path,
                db_filename=db_filename,
                image_dir=image_dir,
                archive_dir=archive_dir,
                max_disk_usage_pct=max_disk_usage,
                auto_cleanup=auto_cleanup
            )
            logger.info("Data store initialized")
            
            # Start Telegram bot if configured
            token_file = self.config.get("telegram.token_file")
            if token_file:
                # Load environment variables from .env file
                env_path = Path(token_file)
                if env_path.exists():
                    load_dotenv(dotenv_path=env_path)
                    logger.info(f"Loaded environment variables from {env_path}")
                else:
                    logger.warning(f"Telegram token file not found at {env_path}")

                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                chat_id = os.getenv("TELEGRAM_CHAT_ID")

                if not bot_token or bot_token == "your_bot_token_here":
                    logger.warning("TELEGRAM_BOT_TOKEN not found or not set in .env file. Telegram bot not starting.")
                else:
                    self.telegram_bot = TurtleBot(
                        token=bot_token,
                        chat_id=chat_id
                    )
                    self.telegram_sender = AsyncTelegramSender(self.telegram_bot)
            
            # Initialize components
            self._init_components()
            
            # Start Telegram bot and send startup notification
            if self.telegram_bot:
                self.telegram_bot.start()
                logger.info("Telegram bot started")
                self.telegram_sender.send_message("🐢 TurtleCam system is starting up!")
            
            # Enter main loop
            self._main_loop()
            
        except Exception as e:
            logger.error(f"Error starting TurtleCam: {e}", exc_info=True)
            self.stop()
            
    def _init_components(self):
        """Initialize system components."""
        try:
            testing_mode = self.config.get("system.testing_mode", False)

            # Initialize environmental sensor
            self.sensor = DHT22Sensor(
                pin=self.config.get("environment.sensor_pin", 4),
                poll_interval=self.config.get("environment.poll_interval_sec", 60),
                db_path=self.data_store.db_path,
                mock_mode=testing_mode
            )
            self.sensor.start()
            logger.info("Environmental sensor started")

            # Initialize environmental alerts
            self.alert_monitor = EnvAlertMonitor(
                sensor=self.sensor,
                telegram_sender=self.telegram_sender,
                check_interval=self.config.get("environment.poll_interval_sec", 60),
                temp_low_threshold=self.config.get("environment.temp_low_threshold", 22.0),
                temp_high_threshold=self.config.get("environment.temp_high_threshold", 33.0),
                alert_cooldown_minutes=self.config.get("environment.alert_cooldown_min", 15)
            )

            # Initialize relay controller
            self.relay = RelayController(
                config_path=self.config.get("relay.config_path", "config/relay.yaml"),
                mock_mode=self.config.get("relay.mock_mode", False) or testing_mode
            )

            # Register safety callback and start components
            self.alert_monitor.register_safety_callback(self.relay.handle_high_temperature)
            self.alert_monitor.start()
            self.relay.start()
            logger.info("Relay controller and alert monitor started")

            # Initialize vision system
            vision_config = self.config.get_section("vision")
            vision_config['testing_mode'] = testing_mode
            vision_config['data_store'] = self.data_store
            vision_config['telegram_sender'] = self.telegram_sender

            self.vision = VisionOrchestrator(**vision_config)
            self.vision.start()
            logger.info("Vision system started")

            # Connect Telegram bot commands to components
            self._connect_telegram_commands()

        except Exception as e:
            logger.error(f"Error initializing components: {e}", exc_info=True)
            raise
    
    def _connect_telegram_commands(self):
        """Connect Telegram bot commands to system components."""
        try:
            # Connect commands if bot is available
            if self.telegram_bot and self.telegram_bot.application:
                # Store components in bot for command handlers
                self.telegram_bot.register_components(
                    vision=self.vision,
                    sensor=self.sensor,
                    alert_monitor=self.alert_monitor,
                    relay_controller=self.relay,
                    data_store=self.data_store
                )
                
                logger.info("Telegram commands connected to components")
        except Exception as e:
            logger.error(f"Error connecting Telegram commands: {e}")
    
    def _main_loop(self):
        """Main application loop."""
        maintenance_interval = 3600  # Run maintenance tasks every hour
        last_maintenance = time.time()
        
        try:
            logger.info("Entering main loop")
            
            while self.running:
                # Perform periodic maintenance
                now = time.time()
                if now - last_maintenance >= maintenance_interval:
                    self._run_maintenance_tasks()
                    last_maintenance = now
                
                # Check if components are still running
                self._check_component_health()
                
                # Sleep to avoid tight loop
                time.sleep(10)
                
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
        finally:
            self.stop()
    
    def _run_maintenance_tasks(self):
        """Run periodic maintenance tasks."""
        try:
            logger.info("Running maintenance tasks")
            
            # Check disk usage
            disk_usage = self.data_store.check_disk_usage()
            logger.info(f"Disk usage: {disk_usage.get('usage_pct', 0):.1f}%")
            
            # Archive old data periodically
            retention_days = self.config.get("storage.retention_days", 30)
            archive_results = self.data_store.archive_old_data(days_threshold=retention_days)
            logger.info(f"Archived {archive_results.get('crops_archived', 0)} old crops")
            
        except Exception as e:
            logger.error(f"Error running maintenance: {e}")
    
    def _check_component_health(self):
        """Check if essential components are still running."""
        try:
            # Check vision system
            if self.vision and not self.vision.is_running():
                logger.warning("Vision system stopped unexpectedly, attempting restart")
                try:
                    self.vision.start()
                except Exception as e:
                    logger.error(f"Failed to restart vision system: {e}")
            
            # Check sensor
            if self.sensor and hasattr(self.sensor, 'poll_thread') and \
               self.sensor.poll_thread and not self.sensor.poll_thread.is_alive():
                logger.warning("Sensor polling stopped unexpectedly, attempting restart")
                try:
                    self.sensor.start()
                except Exception as e:
                    logger.error(f"Failed to restart sensor: {e}")
            
        except Exception as e:
            logger.error(f"Error checking component health: {e}")
    
    def stop(self):
        """Stop the TurtleCam application."""
        if not self.running:
            return
            
        logger.info("Stopping TurtleCam")
        self.running = False
        
        try:
            # Send shutdown notification
            if self.telegram_sender:
                self.telegram_sender.send_message("🐢 TurtleCam system is shutting down")
            
            # Stop components in reverse order
            if self.vision:
                self.vision.stop()
                logger.info("Vision system stopped")
                
            if self.relay:
                self.relay.stop()
                logger.info("Relay controller stopped")
                
            if self.alert_monitor:
                self.alert_monitor.stop()
                logger.info("Alert monitor stopped")
                
            if self.sensor:
                self.sensor.stop()
                logger.info("Environmental sensor stopped")
                
            # Stop Telegram bot last
            if self.telegram_bot:
                self.telegram_bot.stop()
                logger.info("Telegram bot stopped")
                
        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)


def main():
    """Main entry point."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="TurtleCam Smart Terrarium Controller")
    parser.add_argument("--config", help="Path to configuration file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    
    # Set up basic logging until config is loaded
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create and start TurtleCam
    app = TurtleCam(config_path=args.config)
    app.start()


if __name__ == "__main__":
    main()
