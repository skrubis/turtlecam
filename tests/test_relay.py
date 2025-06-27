"""Tests for Relay Controller module."""

import unittest
from unittest.mock import MagicMock, patch
import tempfile
import yaml
import time
from pathlib import Path

from turtlecam.relay.controller import RelayController


class TestRelayController(unittest.TestCase):
    """Test cases for RelayController class."""
    
    def setUp(self):
        """Set up test environment."""
        # Create temp directory for config files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "test_config.yaml"
        
        # Create a test config file
        self.test_config = {
            "relay": {
                "pins": {
                    "light": 17,
                    "heat": 27,
                    "filter": 22,
                    "fan": 23
                },
                "schedule": {
                    "light": [
                        {"on": "08:00", "off": "20:00"}
                    ],
                    "heat": [
                        {"on": "06:00", "off": "22:00", "condition": "temp_below:25"}
                    ],
                    "filter": [
                        {"on": "00:00", "off": "23:59"}
                    ],
                    "fan": [
                        {"on": "12:00", "off": "14:00"},
                        {"on": "18:00", "off": "20:00"}
                    ]
                }
            }
        }
        
        # Write config to file
        with open(self.config_path, 'w') as f:
            yaml.dump(self.test_config, f)
        
        # Mock dependencies
        self.mock_data_store = MagicMock()
    
    def tearDown(self):
        """Clean up test environment."""
        self.temp_dir.cleanup()
    
    def test_init(self):
        """Test controller initialization."""
        controller = RelayController(
            config_path=self.config_path,
            data_store=self.mock_data_store,
            mock_mode=True
        )
        
        # Check pins were set up correctly
        self.assertEqual(controller.pins["light"], 17)
        self.assertEqual(controller.pins["heat"], 27)
        self.assertEqual(controller.pins["filter"], 22)
        self.assertEqual(controller.pins["fan"], 23)
        
        # Check schedule was loaded
        self.assertEqual(len(controller.schedules["light"]), 1)
        self.assertEqual(len(controller.schedules["fan"]), 2)
        
        # Check that controller is not running yet
        self.assertFalse(controller.running)
    
    @patch('turtlecam.relay.controller.RPi.GPIO')
    def test_init_gpio(self, mock_gpio):
        """Test GPIO initialization."""
        controller = RelayController(
            config_path=self.config_path,
            data_store=self.mock_data_store,
            mock_mode=False
        )
        
        # Initialize GPIO
        controller._init_gpio()
        
        # Check GPIO was set up correctly
        mock_gpio.setmode.assert_called_once_with(mock_gpio.BCM)
        self.assertEqual(mock_gpio.setup.call_count, 4)  # 4 pins
        
        # Check all pins are initially off (HIGH means off for most relay boards)
        self.assertEqual(mock_gpio.output.call_count, 4)
    
    def test_start_stop(self):
        """Test starting and stopping the controller."""
        controller = RelayController(
            config_path=self.config_path,
            data_store=self.mock_data_store,
            mock_mode=True
        )
        
        # Start controller
        controller.start()
        self.assertTrue(controller.running)
        
        # Stop controller
        controller.stop()
        self.assertFalse(controller.running)
    
    def test_set_relay(self):
        """Test setting relay state."""
        controller = RelayController(
            config_path=self.config_path,
            data_store=self.mock_data_store,
            mock_mode=True
        )
        
        # Initialize state
        controller._init_gpio()
        
        # Turn on light relay
        controller.set_relay("light", True)
        
        # Check state
        self.assertTrue(controller.relay_states["light"])
        
        # Turn it off
        controller.set_relay("light", False)
        
        # Check state
        self.assertFalse(controller.relay_states["light"])
    
    def test_manual_override(self):
        """Test manual override of relay state."""
        controller = RelayController(
            config_path=self.config_path,
            data_store=self.mock_data_store,
            mock_mode=True
        )
        
        # Initialize state
        controller._init_gpio()
        
        # Set manual override for light
        controller.manual_override("light", True, 1)  # 1 second duration
        
        # Check state and override
        self.assertTrue(controller.relay_states["light"])
        self.assertTrue(controller.overrides["light"]["active"])
        
        # Wait for override to expire
        time.sleep(1.5)
        
        # Process schedule once to clear override
        controller._process_schedules()
        
        # Check override expired
        self.assertFalse(controller.overrides["light"]["active"])
    
    def test_safety_shutdown(self):
        """Test safety shutdown procedure."""
        controller = RelayController(
            config_path=self.config_path,
            data_store=self.mock_data_store,
            mock_mode=True
        )
        
        # Initialize state
        controller._init_gpio()
        
        # Turn on heat
        controller.set_relay("heat", True)
        self.assertTrue(controller.relay_states["heat"])
        
        # Turn on fan
        controller.set_relay("fan", False)
        self.assertFalse(controller.relay_states["fan"])
        
        # Trigger safety shutdown
        controller.handle_safety_event("high_temp")
        
        # Heat should be off, fan should be on
        self.assertFalse(controller.relay_states["heat"])
        self.assertTrue(controller.relay_states["fan"])
        
        # Safety override should be active for heat
        self.assertTrue(controller.overrides["heat"]["active"])
        self.assertEqual(controller.overrides["heat"]["reason"], "SAFETY:high_temp")


if __name__ == '__main__':
    unittest.main()
