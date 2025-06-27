"""Tests for Environmental Monitoring module."""

import unittest
from unittest.mock import MagicMock, patch
import tempfile
import time
from pathlib import Path

from turtlecam.env_monitor.sensor import DHT22Sensor
from turtlecam.env_monitor.alerting import EnvAlertMonitor


class TestDHT22Sensor(unittest.TestCase):
    """Test cases for DHT22Sensor class."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_turtlecam.db"
        
        # Create mock data store
        self.mock_data_store = MagicMock()
        self.mock_data_store.db_path = str(self.db_path)
    
    def tearDown(self):
        """Clean up test environment."""
        self.temp_dir.cleanup()
    
    def test_init(self):
        """Test sensor initialization."""
        sensor = DHT22Sensor(
            data_store=self.mock_data_store,
            pin=4,
            poll_interval=30,
            mock_mode=True
        )
        
        self.assertTrue(sensor.mock_mode)
        self.assertEqual(sensor.pin, 4)
        self.assertEqual(sensor.poll_interval, 30)
        self.assertFalse(sensor.running)
    
    def test_start_stop(self):
        """Test starting and stopping the sensor."""
        sensor = DHT22Sensor(
            data_store=self.mock_data_store,
            pin=4,
            poll_interval=1,
            mock_mode=True
        )
        
        # Start sensor
        sensor.start()
        self.assertTrue(sensor.running)
        
        # Wait briefly for at least one reading
        time.sleep(2)
        
        # Stop sensor
        sensor.stop()
        self.assertFalse(sensor.running)
        
        # Check that we got at least one reading
        self.assertGreaterEqual(sensor.readings_count, 1)
        self.assertIsNotNone(sensor.last_temperature)
        self.assertIsNotNone(sensor.last_humidity)
    
    def test_mock_readings(self):
        """Test mock sensor readings."""
        sensor = DHT22Sensor(
            data_store=self.mock_data_store,
            pin=4,
            poll_interval=1,
            mock_mode=True
        )
        
        # Take a reading
        temp, humidity = sensor._get_reading()
        
        # Check that values are in the expected ranges
        self.assertTrue(18 <= temp <= 32)
        self.assertTrue(40 <= humidity <= 80)


class TestEnvAlertMonitor(unittest.TestCase):
    """Test cases for EnvAlertMonitor class."""
    
    def setUp(self):
        """Set up test environment."""
        # Mock dependencies
        self.mock_telegram_bot = MagicMock()
        self.mock_sensor = MagicMock()
        self.mock_safety_callback = MagicMock()
        
        # Set up test temperatures
        self.mock_sensor.get_temperature.return_value = 25.0
    
    def test_init(self):
        """Test alert monitor initialization."""
        monitor = EnvAlertMonitor(
            telegram_bot=self.mock_telegram_bot,
            sensor=self.mock_sensor,
            min_temp=20,
            max_temp=35,
            safety_callback=self.mock_safety_callback
        )
        
        self.assertEqual(monitor.min_temp, 20)
        self.assertEqual(monitor.max_temp, 35)
        self.assertFalse(monitor.running)
    
    def test_check_temperature_normal(self):
        """Test temperature check within normal range."""
        monitor = EnvAlertMonitor(
            telegram_bot=self.mock_telegram_bot,
            sensor=self.mock_sensor,
            min_temp=20,
            max_temp=35,
            safety_callback=self.mock_safety_callback
        )
        
        # Temperature is within range
        self.mock_sensor.get_temperature.return_value = 25.0
        monitor._check_temperature()
        
        # No alerts should be sent
        self.mock_telegram_bot.send_message.assert_not_called()
        self.mock_safety_callback.assert_not_called()
    
    def test_check_temperature_too_cold(self):
        """Test temperature check when too cold."""
        monitor = EnvAlertMonitor(
            telegram_bot=self.mock_telegram_bot,
            sensor=self.mock_sensor,
            min_temp=20,
            max_temp=35,
            safety_callback=self.mock_safety_callback,
            alert_cooldown=0  # Disable cooldown for testing
        )
        
        # Temperature is too cold
        self.mock_sensor.get_temperature.return_value = 18.0
        monitor._check_temperature()
        
        # Alert should be sent
        self.mock_telegram_bot.send_message.assert_called_once()
        self.assertIn("LOW TEMPERATURE", self.mock_telegram_bot.send_message.call_args[0][0])
    
    def test_check_temperature_too_hot(self):
        """Test temperature check when too hot."""
        monitor = EnvAlertMonitor(
            telegram_bot=self.mock_telegram_bot,
            sensor=self.mock_sensor,
            min_temp=20,
            max_temp=35,
            safety_callback=self.mock_safety_callback,
            alert_cooldown=0  # Disable cooldown for testing
        )
        
        # Temperature is too hot
        self.mock_sensor.get_temperature.return_value = 37.0
        monitor._check_temperature()
        
        # Alert should be sent
        self.mock_telegram_bot.send_message.assert_called_once()
        self.assertIn("HIGH TEMPERATURE", self.mock_telegram_bot.send_message.call_args[0][0])
    
    def test_safety_action(self):
        """Test safety action trigger on persistent high temperature."""
        monitor = EnvAlertMonitor(
            telegram_bot=self.mock_telegram_bot,
            sensor=self.mock_sensor,
            min_temp=20,
            max_temp=35,
            safety_callback=self.mock_safety_callback,
            alert_cooldown=0,  # Disable cooldown for testing
            safety_threshold_minutes=0.01  # Set very short threshold for testing (0.6 seconds)
        )
        
        # Temperature is too hot
        self.mock_sensor.get_temperature.return_value = 37.0
        monitor._check_temperature()
        
        # Wait for safety threshold to be reached
        time.sleep(1)
        
        # Check temperature again
        monitor._check_temperature()
        
        # Safety callback should be called
        self.mock_safety_callback.assert_called_once()
        self.assertIn("high_temp", self.mock_safety_callback.call_args[0])


if __name__ == '__main__':
    unittest.main()
