"""Tests for Data Store module."""

import unittest
from unittest.mock import MagicMock, patch
import tempfile
import sqlite3
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta

from turtlecam.storage.data_store import DataStore


class TestDataStore(unittest.TestCase):
    """Test cases for DataStore class."""
    
    def setUp(self):
        """Set up test environment."""
        # Create temporary directory
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)
        
        # Define paths
        self.db_path = self.base_path / "test_turtlecam.db"
        self.image_path = self.base_path / "images"
        self.archive_path = self.base_path / "archive"
        
        # Create directories
        self.image_path.mkdir(exist_ok=True)
        self.archive_path.mkdir(exist_ok=True)
    
    def tearDown(self):
        """Clean up test environment."""
        self.temp_dir.cleanup()
    
    def test_init(self):
        """Test data store initialization."""
        data_store = DataStore(
            base_path=self.base_path,
            db_file="test_turtlecam.db"
        )
        
        # Check paths
        self.assertEqual(data_store.base_path, self.base_path)
        self.assertEqual(data_store.db_path, self.db_path)
        self.assertEqual(data_store.image_path, self.image_path)
        self.assertEqual(data_store.archive_path, self.archive_path)
        
        # Check database was created
        self.assertTrue(self.db_path.exists())
        
        # Check schema tables
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        # Verify tables exist
        expected_tables = [
            "motion_events", "crops", "env_logs", "relay_logs", 
            "export_logs", "system_logs"
        ]
        for table in expected_tables:
            self.assertIn(table, tables)
    
    def test_get_date_path(self):
        """Test date path generation."""
        data_store = DataStore(
            base_path=self.base_path,
            db_file="test_turtlecam.db"
        )
        
        # Test with specific date
        test_date = datetime(2023, 6, 15, 12, 30, 45)
        path = data_store._get_date_path(self.image_path, test_date)
        
        # Check path structure
        self.assertEqual(path, self.image_path / "2023-06" / "15")
    
    def test_log_motion_event(self):
        """Test logging motion events."""
        data_store = DataStore(
            base_path=self.base_path,
            db_file="test_turtlecam.db"
        )
        
        # Create test GIF path
        gif_path = self.image_path / "test.gif"
        
        # Log a motion event
        metadata = {"motion_area": 0.25, "motion_pixels": 10000}
        event_id = data_store.log_motion_event(str(gif_path), metadata)
        
        # Check ID was returned
        self.assertIsNotNone(event_id)
        
        # Verify database record
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM motion_events WHERE id=?", (event_id,))
        row = cursor.fetchone()
        conn.close()
        
        # Check record values
        self.assertEqual(row["gif_path"], str(gif_path))
        self.assertIsNotNone(row["timestamp"])
        self.assertEqual(row["metadata"], '{"motion_area": 0.25, "motion_pixels": 10000}')
    
    def test_log_crop(self):
        """Test logging crop events."""
        data_store = DataStore(
            base_path=self.base_path,
            db_file="test_turtlecam.db"
        )
        
        # Create test crop path
        crop_path = self.image_path / "crop.jpg"
        
        # Create parent motion event
        metadata = {"motion_area": 0.25, "motion_pixels": 10000}
        event_id = data_store.log_motion_event(str(self.image_path / "test.gif"), metadata)
        
        # Log a crop
        crop_id = data_store.log_crop(
            event_id=event_id,
            crop_path=str(crop_path),
            x=100, y=150,
            width=200, height=100,
            confidence=0.85,
            label="turtle"
        )
        
        # Check ID was returned
        self.assertIsNotNone(crop_id)
        
        # Verify database record
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM crops WHERE id=?", (crop_id,))
        row = cursor.fetchone()
        conn.close()
        
        # Check record values
        self.assertEqual(row["event_id"], event_id)
        self.assertEqual(row["crop_path"], str(crop_path))
        self.assertEqual(row["x"], 100)
        self.assertEqual(row["y"], 150)
        self.assertEqual(row["width"], 200)
        self.assertEqual(row["height"], 100)
        self.assertEqual(row["confidence"], 0.85)
        self.assertEqual(row["label"], "turtle")
    
    def test_log_env_data(self):
        """Test logging environmental data."""
        data_store = DataStore(
            base_path=self.base_path,
            db_file="test_turtlecam.db"
        )
        
        # Log temperature and humidity
        data_store.log_env_data(temperature=25.5, humidity=65.0)
        
        # Verify database record
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM env_logs ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        
        # Check record values
        self.assertEqual(row["temperature"], 25.5)
        self.assertEqual(row["humidity"], 65.0)
    
    def test_log_relay_change(self):
        """Test logging relay state changes."""
        data_store = DataStore(
            base_path=self.base_path,
            db_file="test_turtlecam.db"
        )
        
        # Log relay change
        data_store.log_relay_change(relay="light", state=True, reason="schedule")
        
        # Verify database record
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM relay_logs ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        
        # Check record values
        self.assertEqual(row["relay"], "light")
        self.assertEqual(row["state"], 1)
        self.assertEqual(row["reason"], "schedule")
    
    def test_get_env_data_range(self):
        """Test retrieving environmental data range."""
        data_store = DataStore(
            base_path=self.base_path,
            db_file="test_turtlecam.db"
        )
        
        # Insert some test data
        for i in range(10):
            temp = 20 + i * 0.5
            humidity = 60 + i
            data_store.log_env_data(temperature=temp, humidity=humidity)
        
        # Get data range
        data = data_store.get_env_data_range(
            hours=24,
            limit=5
        )
        
        # Check data
        self.assertEqual(len(data), 5)
        self.assertIn("timestamp", data[0])
        self.assertIn("temperature", data[0])
        self.assertIn("humidity", data[0])
    
    def test_create_subdirectories(self):
        """Test creating date-based subdirectories."""
        data_store = DataStore(
            base_path=self.base_path,
            db_file="test_turtlecam.db"
        )
        
        # Get image path for today
        today = datetime.now()
        path = data_store._get_date_path(self.image_path, today)
        
        # Ensure the path exists
        self.assertTrue(path.exists())
        self.assertTrue(path.is_dir())
    
    @patch('turtlecam.storage.data_store.shutil.disk_usage')
    def test_check_disk_usage(self, mock_disk_usage):
        """Test disk usage check functionality."""
        # Mock disk_usage to return specific values
        mock_disk_usage.return_value = MagicMock(
            total=100*1024*1024*1024,  # 100GB
            used=80*1024*1024*1024,    # 80GB
            free=20*1024*1024*1024     # 20GB
        )
        
        data_store = DataStore(
            base_path=self.base_path,
            db_file="test_turtlecam.db"
        )
        
        # Check disk usage
        usage = data_store.check_disk_usage()
        
        # Verify usage values
        self.assertEqual(usage["total_gb"], 100)
        self.assertEqual(usage["used_gb"], 80)
        self.assertEqual(usage["free_gb"], 20)
        self.assertEqual(usage["usage_pct"], 80.0)


if __name__ == '__main__':
    unittest.main()
