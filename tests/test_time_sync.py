"""Tests for Time Synchronization module."""

import unittest
from unittest.mock import MagicMock, patch
import tempfile
import time
from datetime import datetime
from pathlib import Path

from turtlecam.time_sync.sync_manager import TimeSync


class TestTimeSync(unittest.TestCase):
    """Test cases for TimeSync class."""
    
    def setUp(self):
        """Set up test environment."""
        pass
    
    def tearDown(self):
        """Clean up test environment."""
        pass
    
    def test_init(self):
        """Test time sync initialization."""
        # Test in mock mode
        sync = TimeSync(
            use_rtc=True,
            rtc_module="DS3231",
            ntp_server="pool.ntp.org",
            mock_mode=True
        )
        
        self.assertTrue(sync.mock_mode)
        self.assertEqual(sync.ntp_server, "pool.ntp.org")
        self.assertFalse(sync.running)
    
    @patch('turtlecam.time_sync.sync_manager.socket.create_connection')
    @patch('turtlecam.time_sync.sync_manager.subprocess.run')
    def test_ntp_sync(self, mock_run, mock_create_connection):
        """Test NTP synchronization."""
        # Mock successful connection
        mock_create_connection.return_value = True
        
        # Mock successful subprocess run
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        
        sync = TimeSync(mock_mode=True)
        
        # Test NTP sync
        result = sync._sync_with_ntp()
        
        # Verify results
        self.assertTrue(result)
        self.assertEqual(sync.ntp_sync_count, 1)
        self.assertEqual(sync.ntp_sync_failures, 0)
    
    @patch('turtlecam.time_sync.sync_manager.socket.create_connection')
    def test_connectivity_check(self, mock_create_connection):
        """Test internet connectivity check."""
        # Mock successful connection
        mock_create_connection.return_value = True
        
        sync = TimeSync(mock_mode=True)
        
        # Test connectivity check
        result = sync._check_connectivity()
        
        # Verify result
        self.assertTrue(result)
        
        # Test failed connectivity
        mock_create_connection.side_effect = OSError("No connection")
        result = sync._check_connectivity()
        
        # Verify result
        self.assertFalse(result)
    
    def test_start_stop(self):
        """Test starting and stopping time sync."""
        sync = TimeSync(
            mock_mode=True,
            sync_interval_hours=0.001  # Very short interval for testing
        )
        
        # Start sync
        sync.start()
        self.assertTrue(sync.running)
        
        # Wait briefly for sync to happen
        time.sleep(1)
        
        # Stop sync
        sync.stop()
        self.assertFalse(sync.running)
        
        # Check that NTP sync was attempted
        self.assertEqual(sync.ntp_sync_count, 1)
    
    @patch('turtlecam.time_sync.sync_manager.subprocess.run')
    def test_sync_system_from_rtc(self, mock_run):
        """Test syncing system time from RTC."""
        # Mock successful subprocess run
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        
        sync = TimeSync(mock_mode=True)
        
        # Test RTC to system sync
        result = sync._sync_system_from_rtc()
        
        # Verify result in mock mode
        self.assertTrue(result)
    
    def test_status(self):
        """Test getting time sync status."""
        sync = TimeSync(
            mock_mode=True,
            ntp_server="test.ntp.org"
        )
        
        # Get status
        status = sync.get_status()
        
        # Verify status contains expected fields
        self.assertEqual(status["ntp_server"], "test.ntp.org")
        self.assertEqual(status["rtc_enabled"], False)
        self.assertEqual(status["running"], False)
        self.assertEqual(status["ntp_sync_count"], 0)


if __name__ == '__main__':
    unittest.main()
