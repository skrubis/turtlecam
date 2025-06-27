"""Data store module for TurtleCam.

This module manages the central SQLite database and directory structure
for the TurtleCam system, ensuring consistent data access patterns.
"""

import os
import logging
import sqlite3
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple

logger = logging.getLogger(__name__)


class DataStore:
    """Central data storage manager for TurtleCam."""
    
    # Database schema version
    SCHEMA_VERSION = 1
    
    def __init__(self, 
                 base_path: str = "data",
                 db_filename: str = "turtlecam.db",
                 image_dir: str = "images",
                 archive_dir: str = "archive",
                 max_disk_usage_pct: float = 85.0,
                 auto_cleanup: bool = True):
        """Initialize the data store.
        
        Args:
            base_path (str): Base directory path for all data
            db_filename (str): SQLite database filename
            image_dir (str): Directory for storing images
            archive_dir (str): Directory for archived data
            max_disk_usage_pct (float): Maximum disk usage percentage
            auto_cleanup (bool): Enable automatic cleanup when disk usage exceeded
        """
        # Set up paths
        self.base_path = Path(base_path).absolute()
        self.db_path = self.base_path / db_filename
        self.image_path = self.base_path / image_dir
        self.archive_path = self.base_path / archive_dir
        
        # Configuration
        self.max_disk_usage_pct = max_disk_usage_pct
        self.auto_cleanup = auto_cleanup
        
        # Initialize storage
        self._init_storage()
        
    def _init_storage(self):
        """Initialize the storage structure."""
        # Create directories if they don't exist
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.image_path.mkdir(parents=True, exist_ok=True)
        self.archive_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
        
        logger.info(f"Initialized data store at {self.base_path}")
        
    def _init_database(self):
        """Initialize the SQLite database with all required tables."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create metadata table for tracking schema version
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS metadata (
                key     TEXT PRIMARY KEY,
                value   TEXT
            )
            ''')
            
            # Create motion_events table if not exists
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS motion_events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       DATETIME NOT NULL,
                duration_sec    REAL,
                frame_count     INTEGER,
                gif_path        TEXT,
                metadata        TEXT
            )
            ''')
            
            # Create crops table if not exists
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS crops (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id        INTEGER REFERENCES motion_events(id),
                timestamp       DATETIME NOT NULL,
                crop_path       TEXT NOT NULL,
                x               INTEGER,
                y               INTEGER,
                width           INTEGER,
                height          INTEGER,
                confidence      REAL,
                label           TEXT,
                is_archived     BOOLEAN DEFAULT 0
            )
            ''')
            
            # Create env_log table if not exists
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS env_log (
                ts              DATETIME PRIMARY KEY,
                temp_c          REAL,
                humidity_pct    REAL
            )
            ''')
            
            # Create relay_log table if not exists
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS relay_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       DATETIME NOT NULL,
                relay_name      TEXT NOT NULL,
                state           BOOLEAN NOT NULL,
                trigger_type    TEXT NOT NULL,
                trigger_source  TEXT
            )
            ''')
            
            # Create export_log table for tracking ML exports
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS export_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp       DATETIME NOT NULL,
                export_path     TEXT NOT NULL,
                export_type     TEXT NOT NULL,
                crop_count      INTEGER,
                start_date      DATETIME,
                end_date        DATETIME
            )
            ''')
            
            # Set schema version if not already set
            cursor.execute('''
            INSERT OR IGNORE INTO metadata (key, value) 
            VALUES ('schema_version', ?)
            ''', (str(self.SCHEMA_VERSION),))
            
            # Commit changes
            conn.commit()
            
            # Check for schema upgrades
            self._check_schema_upgrade(conn)
            
            conn.close()
            logger.info(f"Initialized database at {self.db_path}")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            
    def _check_schema_upgrade(self, conn=None):
        """Check if schema upgrade is needed and perform if necessary.
        
        Args:
            conn (sqlite3.Connection, optional): Existing database connection
        """
        close_conn = False
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            close_conn = True
            
        try:
            cursor = conn.cursor()
            
            # Get current schema version
            cursor.execute('SELECT value FROM metadata WHERE key = "schema_version"')
            result = cursor.fetchone()
            current_version = int(result[0]) if result else 0
            
            if current_version < self.SCHEMA_VERSION:
                logger.info(f"Upgrading database schema from version {current_version} to {self.SCHEMA_VERSION}")
                
                # Perform schema upgrades based on version
                # Add migrations as needed for future versions
                if current_version < 1:
                    # Initial schema created in _init_database
                    pass
                
                # Update schema version
                cursor.execute('''
                UPDATE metadata SET value = ? WHERE key = 'schema_version'
                ''', (str(self.SCHEMA_VERSION),))
                
                conn.commit()
                logger.info(f"Schema upgraded to version {self.SCHEMA_VERSION}")
        
        except Exception as e:
            logger.error(f"Error upgrading schema: {e}")
        
        finally:
            if close_conn and conn:
                conn.close()
                
    def get_connection(self):
        """Get a database connection.
        
        Returns:
            sqlite3.Connection: SQLite connection object
        """
        return sqlite3.connect(self.db_path)
    
    def get_image_dir(self, subdir=None):
        """Get path to image directory, optionally with subdirectory.
        
        Args:
            subdir (str, optional): Optional subdirectory name
            
        Returns:
            Path: Path to requested directory
        """
        if subdir:
            path = self.image_path / subdir
            path.mkdir(parents=True, exist_ok=True)
            return path
        return self.image_path
    
    def get_daily_image_dir(self, date=None):
        """Get path to date-based image directory.
        
        Args:
            date (datetime, optional): Date to use, defaults to today
            
        Returns:
            Path: Path to date-based directory
        """
        if date is None:
            date = datetime.now()
            
        date_str = date.strftime('%Y-%m-%d')
        path = self.image_path / date_str
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_archive_dir(self, subdir=None):
        """Get path to archive directory, optionally with subdirectory.
        
        Args:
            subdir (str, optional): Optional subdirectory name
            
        Returns:
            Path: Path to requested directory
        """
        if subdir:
            path = self.archive_path / subdir
            path.mkdir(parents=True, exist_ok=True)
            return path
        return self.archive_path
    
    def log_motion_event(self, timestamp, duration=None, frame_count=None, gif_path=None, metadata=None):
        """Log a motion event to the database.
        
        Args:
            timestamp (datetime): Event timestamp
            duration (float, optional): Event duration in seconds
            frame_count (int, optional): Number of frames captured
            gif_path (str, optional): Path to generated GIF
            metadata (dict, optional): Additional metadata (will be JSON serialized)
            
        Returns:
            int: Event ID
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Convert metadata to JSON if needed
            if metadata and isinstance(metadata, dict):
                import json
                metadata = json.dumps(metadata)
            
            # Insert motion event
            cursor.execute('''
            INSERT INTO motion_events 
            (timestamp, duration_sec, frame_count, gif_path, metadata)
            VALUES (?, ?, ?, ?, ?)
            ''', (
                timestamp.isoformat(), duration, frame_count, 
                str(gif_path) if gif_path else None, metadata
            ))
            
            # Get the event ID
            event_id = cursor.lastrowid
            
            conn.commit()
            conn.close()
            
            return event_id
            
        except Exception as e:
            logger.error(f"Error logging motion event: {e}")
            return None
    
    def log_crop(self, event_id, timestamp, crop_path, x=None, y=None, 
                width=None, height=None, confidence=None, label=None):
        """Log a crop to the database.
        
        Args:
            event_id (int): Associated motion event ID
            timestamp (datetime): Crop timestamp
            crop_path (str): Path to crop image
            x, y (int, optional): Crop top-left coordinates
            width, height (int, optional): Crop dimensions
            confidence (float, optional): Detection confidence
            label (str, optional): Object label
            
        Returns:
            int: Crop ID
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Insert crop
            cursor.execute('''
            INSERT INTO crops 
            (event_id, timestamp, crop_path, x, y, width, height, confidence, label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                event_id, timestamp.isoformat(), str(crop_path),
                x, y, width, height, confidence, label
            ))
            
            # Get the crop ID
            crop_id = cursor.lastrowid
            
            conn.commit()
            conn.close()
            
            return crop_id
            
        except Exception as e:
            logger.error(f"Error logging crop: {e}")
            return None
    
    def log_relay_change(self, relay_name, state, trigger_type, trigger_source=None, timestamp=None):
        """Log a relay state change.
        
        Args:
            relay_name (str): Name of the relay
            state (bool): New state (True=on, False=off)
            trigger_type (str): What triggered the change (e.g., schedule, manual, safety)
            trigger_source (str, optional): Source of trigger (e.g., user ID, temperature)
            timestamp (datetime, optional): Event timestamp, defaults to now
            
        Returns:
            int: Log entry ID
        """
        if timestamp is None:
            timestamp = datetime.now()
            
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Insert relay log
            cursor.execute('''
            INSERT INTO relay_log 
            (timestamp, relay_name, state, trigger_type, trigger_source)
            VALUES (?, ?, ?, ?, ?)
            ''', (
                timestamp.isoformat(), relay_name, state, trigger_type, trigger_source
            ))
            
            # Get the log ID
            log_id = cursor.lastrowid
            
            conn.commit()
            conn.close()
            
            return log_id
            
        except Exception as e:
            logger.error(f"Error logging relay change: {e}")
            return None
    
    def get_recent_motion_events(self, limit=10):
        """Get recent motion events.
        
        Args:
            limit (int): Maximum number of events to retrieve
            
        Returns:
            list: List of motion events
        """
        try:
            conn = self.get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT * FROM motion_events 
            ORDER BY timestamp DESC 
            LIMIT ?
            ''', (limit,))
            
            events = [dict(row) for row in cursor.fetchall()]
            
            conn.close()
            return events
            
        except Exception as e:
            logger.error(f"Error getting recent motion events: {e}")
            return []
    
    def get_env_readings(self, start_time=None, end_time=None, limit=100):
        """Get environmental readings within a time range.
        
        Args:
            start_time (datetime, optional): Start of time range
            end_time (datetime, optional): End of time range
            limit (int): Maximum number of readings
            
        Returns:
            list: List of environmental readings
        """
        try:
            conn = self.get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Prepare the query based on provided time range
            query = "SELECT * FROM env_log"
            params = []
            
            if start_time or end_time:
                query += " WHERE"
                
                if start_time:
                    query += " ts >= ?"
                    params.append(start_time.isoformat())
                    
                if end_time:
                    if start_time:
                        query += " AND"
                    query += " ts <= ?"
                    params.append(end_time.isoformat())
                    
            query += " ORDER BY ts DESC LIMIT ?"
            params.append(limit)
            
            # Execute the query
            cursor.execute(query, params)
            
            readings = [dict(row) for row in cursor.fetchall()]
            
            conn.close()
            return readings
            
        except Exception as e:
            logger.error(f"Error getting environmental readings: {e}")
            return []
    
    def archive_old_data(self, days_threshold=30):
        """Archive data older than the specified threshold.
        
        Args:
            days_threshold (int): Age threshold in days
            
        Returns:
            dict: Count of archived items by type
        """
        try:
            # Calculate cutoff date
            cutoff_date = datetime.now() - timedelta(days=days_threshold)
            cutoff_str = cutoff_date.isoformat()
            
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Get crops to archive
            cursor.execute('''
            SELECT id, crop_path FROM crops 
            WHERE timestamp < ? AND is_archived = 0
            ''', (cutoff_str,))
            
            crops_to_archive = cursor.fetchall()
            
            # Archive each crop
            archive_count = 0
            for crop_id, crop_path in crops_to_archive:
                try:
                    if crop_path:
                        # Create archive path
                        src_path = Path(crop_path)
                        if src_path.exists():
                            # Create archive directory with date structure
                            date_str = cutoff_date.strftime('%Y-%m')
                            archive_dir = self.get_archive_dir(date_str)
                            
                            # Copy to archive
                            dst_path = archive_dir / src_path.name
                            shutil.copy2(src_path, dst_path)
                            
                            # Mark as archived
                            cursor.execute('''
                            UPDATE crops SET is_archived = 1 WHERE id = ?
                            ''', (crop_id,))
                            
                            archive_count += 1
                            
                except Exception as e:
                    logger.error(f"Error archiving crop {crop_id}: {e}")
            
            # Commit changes
            conn.commit()
            conn.close()
            
            logger.info(f"Archived {archive_count} crops older than {days_threshold} days")
            return {"crops_archived": archive_count}
            
        except Exception as e:
            logger.error(f"Error archiving old data: {e}")
            return {"error": str(e)}
    
    def cleanup_disk_space(self, target_usage_pct=None):
        """Clean up disk space by removing old data.
        
        Args:
            target_usage_pct (float, optional): Target disk usage percentage
            
        Returns:
            dict: Cleanup statistics
        """
        if target_usage_pct is None:
            target_usage_pct = self.max_disk_usage_pct - 10  # Aim for 10% below max
            
        stats = {
            "before_usage_pct": 0,
            "after_usage_pct": 0,
            "deleted_files": 0,
            "freed_bytes": 0
        }
        
        try:
            # Check current disk usage
            disk_usage = shutil.disk_usage(self.base_path)
            current_pct = disk_usage.used / disk_usage.total * 100
            stats["before_usage_pct"] = current_pct
            
            # If usage is below max, no cleanup needed
            if current_pct <= target_usage_pct:
                logger.debug(f"Disk usage {current_pct:.1f}% is below target {target_usage_pct:.1f}%, no cleanup needed")
                stats["after_usage_pct"] = current_pct
                return stats
            
            logger.warning(f"Disk usage {current_pct:.1f}% exceeds target {target_usage_pct:.1f}%, cleaning up")
            
            # Find old crops, oldest first, that have been archived
            conn = self.get_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT id, crop_path FROM crops 
            WHERE is_archived = 1
            ORDER BY timestamp ASC
            ''')
            
            archived_crops = cursor.fetchall()
            
            # Delete archived crops until target usage is reached
            for crop_id, crop_path in archived_crops:
                try:
                    if crop_path:
                        path = Path(crop_path)
                        if path.exists():
                            # Get file size before deleting
                            file_size = path.stat().st_size
                            
                            # Delete the file
                            path.unlink()
                            
                            # Update stats
                            stats["deleted_files"] += 1
                            stats["freed_bytes"] += file_size
                            
                            logger.debug(f"Deleted archived crop: {crop_path}")
                            
                            # Check if we've reached target usage
                            if stats["deleted_files"] % 10 == 0:
                                disk_usage = shutil.disk_usage(self.base_path)
                                current_pct = disk_usage.used / disk_usage.total * 100
                                if current_pct <= target_usage_pct:
                                    break
                                    
                except Exception as e:
                    logger.error(f"Error deleting crop {crop_id}: {e}")
            
            # Check final disk usage
            disk_usage = shutil.disk_usage(self.base_path)
            current_pct = disk_usage.used / disk_usage.total * 100
            stats["after_usage_pct"] = current_pct
            
            logger.info(f"Cleanup: deleted {stats['deleted_files']} files, freed {stats['freed_bytes']/1024/1024:.1f} MB, "
                      f"usage now {current_pct:.1f}%")
            
            conn.close()
            return stats
            
        except Exception as e:
            logger.error(f"Error cleaning up disk space: {e}")
            stats["error"] = str(e)
            return stats
    
    def check_disk_usage(self):
        """Check current disk usage.
        
        Returns:
            dict: Disk usage information
        """
        try:
            disk_usage = shutil.disk_usage(self.base_path)
            usage_pct = disk_usage.used / disk_usage.total * 100
            
            result = {
                "total_bytes": disk_usage.total,
                "used_bytes": disk_usage.used,
                "free_bytes": disk_usage.free,
                "usage_pct": usage_pct,
                "exceeds_threshold": usage_pct > self.max_disk_usage_pct
            }
            
            # Trigger cleanup if needed and auto_cleanup is enabled
            if result["exceeds_threshold"] and self.auto_cleanup:
                logger.warning(f"Disk usage {usage_pct:.1f}% exceeds threshold {self.max_disk_usage_pct:.1f}%, "
                              "initiating automatic cleanup")
                self.cleanup_disk_space()
            
            return result
            
        except Exception as e:
            logger.error(f"Error checking disk usage: {e}")
            return {"error": str(e)}
    
    def log_ml_export(self, export_path, export_type, crop_count, start_date=None, end_date=None):
        """Log a machine learning data export.
        
        Args:
            export_path (str): Path to exported data
            export_type (str): Type of export (e.g., 'yolo', 'tensorflow')
            crop_count (int): Number of crops exported
            start_date, end_date (datetime, optional): Date range of export
            
        Returns:
            int: Export log ID
        """
        try:
            conn = self.get_connection()
            cursor = conn.cursor()
            
            # Insert export log
            cursor.execute('''
            INSERT INTO export_log 
            (timestamp, export_path, export_type, crop_count, start_date, end_date)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                datetime.now().isoformat(), str(export_path), export_type, crop_count,
                start_date.isoformat() if start_date else None,
                end_date.isoformat() if end_date else None
            ))
            
            # Get the log ID
            log_id = cursor.lastrowid
            
            conn.commit()
            conn.close()
            
            return log_id
            
        except Exception as e:
            logger.error(f"Error logging ML export: {e}")
            return None
