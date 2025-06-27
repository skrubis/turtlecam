"""CropStore module for TurtleCam.

This module manages the storage of high-resolution camera crops and associated metadata.
It handles writing to file system and recording detection data to SQLite.
"""

import os
import json
import logging
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class CropStore:
    """Manages storage of camera crops and detection metadata.
    
    Handles saving image files to disk and recording detection data in SQLite.
    Also provides functionality for archiving and cleanup of old data.
    """
    
    def __init__(self, 
                 base_dir="data/crops",
                 db_path="data/turtlecam.db",
                 max_age_days=30,
                 max_disk_percent=80):
        """Initialize the crop store.
        
        Args:
            base_dir (str): Base directory for storing image crops
            db_path (str): Path to SQLite database
            max_age_days (int): Maximum age in days before data cleanup
            max_disk_percent (int): Maximum disk usage percentage before cleanup
        """
        self.base_dir = Path(base_dir)
        self.db_path = Path(db_path)
        self.max_age_days = max_age_days
        self.max_disk_percent = max_disk_percent
        
        # Create directories if they don't exist
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database
        self._init_database()
    
    def _init_database(self):
        """Initialize the SQLite database schema if needed."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Create detections table if not exists
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS detections (
                ts            DATETIME PRIMARY KEY,
                bbox_x        INTEGER,
                bbox_y        INTEGER,
                bbox_w        INTEGER,
                bbox_h        INTEGER,
                confidence    REAL DEFAULT 1.0,
                img_path      TEXT
            )
            ''')
            
            conn.commit()
            conn.close()
            logger.info(f"Initialized database at {self.db_path}")
            
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
    
    def save_crop(self, image_path, bbox, timestamp=None, confidence=1.0):
        """Save crop metadata to database.
        
        Args:
            image_path (str or Path): Path to the saved image file
            bbox (tuple): Bounding box (x, y, w, h)
            timestamp (datetime, optional): Detection timestamp, defaults to now
            confidence (float): Detection confidence (placeholder for future YOLO)
            
        Returns:
            bool: True if successfully saved
        """
        if timestamp is None:
            timestamp = datetime.now()
            
        try:
            # Convert path to relative if it's within base_dir
            image_path = Path(image_path)
            if str(image_path).startswith(str(self.base_dir)):
                rel_path = image_path.relative_to(self.base_dir)
                db_img_path = str(rel_path)
            else:
                db_img_path = str(image_path)
            
            # Extract bbox components
            x, y, w, h = bbox
            
            # Connect to database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Insert record
            cursor.execute('''
            INSERT INTO detections (ts, bbox_x, bbox_y, bbox_w, bbox_h, confidence, img_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                timestamp.isoformat(), x, y, w, h, confidence, db_img_path
            ))
            
            conn.commit()
            conn.close()
            
            logger.debug(f"Saved crop metadata to database: {timestamp.isoformat()}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving crop metadata: {e}")
            return False
    
    def get_crop_path(self, timestamp=None):
        """Generate a path for saving a new crop.
        
        Args:
            timestamp (datetime, optional): Timestamp, defaults to current time
            
        Returns:
            Path: Path object for saving the crop image
        """
        if timestamp is None:
            timestamp = datetime.now()
            
        # Format: data/crops/YYYY/MM/DD/HHMMSS.jpg
        year_month_day = timestamp.strftime("%Y/%m/%d")
        filename = timestamp.strftime("%H%M%S.jpg")
        
        dir_path = self.base_dir / year_month_day
        dir_path.mkdir(parents=True, exist_ok=True)
        
        return dir_path / filename
    
    def get_latest_crops(self, limit=10):
        """Get latest crop records from database.
        
        Args:
            limit (int): Maximum number of records to return
            
        Returns:
            list: List of dicts with crop metadata
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT ts, bbox_x, bbox_y, bbox_w, bbox_h, confidence, img_path
            FROM detections
            ORDER BY ts DESC
            LIMIT ?
            ''', (limit,))
            
            results = []
            for row in cursor.fetchall():
                # Convert row to dict
                record = dict(row)
                
                # Convert image path to absolute if it's relative
                img_path = record['img_path']
                if not os.path.isabs(img_path):
                    record['img_path'] = str(self.base_dir / img_path)
                
                results.append(record)
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"Error fetching latest crops: {e}")
            return []
    
    def archive_old_crops(self, days_threshold=None):
        """Archive old crops into daily TAR files.
        
        Args:
            days_threshold (int, optional): Archive crops older than this many days
            
        Returns:
            int: Number of files archived
        """
        if days_threshold is None:
            days_threshold = 7  # Default: archive after a week
            
        cutoff_date = datetime.now() - timedelta(days=days_threshold)
        cutoff_str = cutoff_date.strftime("%Y-%m-%d")
        
        try:
            import tarfile
            from glob import glob
            
            # Create archives directory
            archives_dir = self.base_dir / "archives"
            archives_dir.mkdir(exist_ok=True)
            
            # Find old directories by date pattern
            year_dirs = list(self.base_dir.glob("[0-9][0-9][0-9][0-9]"))
            
            files_archived = 0
            for year_dir in year_dirs:
                if not year_dir.is_dir() or year_dir.name == "archives":
                    continue
                    
                # Process month directories
                for month_dir in year_dir.glob("[0-9][0-9]"):
                    if not month_dir.is_dir():
                        continue
                        
                    # Process day directories
                    for day_dir in month_dir.glob("[0-9][0-9]"):
                        if not day_dir.is_dir():
                            continue
                            
                        # Check if directory is old enough to archive
                        dir_date = f"{year_dir.name}-{month_dir.name}-{day_dir.name}"
                        if dir_date >= cutoff_str:
                            logger.debug(f"Skipping recent directory: {dir_date}")
                            continue
                        
                        # Create a tar archive for this day
                        tar_path = archives_dir / f"crops_{dir_date}.tar"
                        
                        if tar_path.exists():
                            logger.warning(f"Archive already exists: {tar_path}")
                            continue
                            
                        logger.info(f"Archiving crops from {dir_date} to {tar_path}")
                        
                        with tarfile.open(tar_path, "w") as tar:
                            # Add all files from this day directory
                            for file_path in day_dir.glob("**/*"):
                                if file_path.is_file():
                                    # Add file to tar with path relative to base_dir
                                    rel_path = file_path.relative_to(self.base_dir)
                                    tar.add(file_path, arcname=str(rel_path))
                                    files_archived += 1
                        
                        # Remove the original directory after successful archival
                        if tar_path.exists():
                            shutil.rmtree(day_dir)
                            
            return files_archived
                        
        except Exception as e:
            logger.error(f"Error archiving old crops: {e}")
            return 0
    
    def cleanup_old_data(self, force=False):
        """Clean up old data based on age and disk usage.
        
        Args:
            force (bool): If True, ignore disk usage check
            
        Returns:
            int: Number of archives removed
        """
        try:
            # Check disk usage if not forced
            if not force:
                import shutil
                disk_usage = shutil.disk_usage(self.base_dir)
                percent_used = (disk_usage.used / disk_usage.total) * 100
                
                if percent_used < self.max_disk_percent:
                    logger.debug(f"Disk usage {percent_used:.1f}% below threshold {self.max_disk_percent}%, skipping cleanup")
                    return 0
                
                logger.info(f"Disk usage {percent_used:.1f}% exceeds threshold {self.max_disk_percent}%, cleaning up...")
            
            # Calculate cutoff date
            cutoff_date = datetime.now() - timedelta(days=self.max_age_days)
            cutoff_str = cutoff_date.strftime("%Y-%m-%d")
            
            # Find archives older than cutoff
            archives_dir = self.base_dir / "archives"
            if not archives_dir.exists():
                return 0
                
            removed_count = 0
            
            # Find and remove old archive files
            for archive_path in archives_dir.glob("crops_*.tar"):
                # Extract date from filename (format: crops_YYYY-MM-DD.tar)
                filename = archive_path.name
                if len(filename) < 16:  # Basic validation
                    continue
                    
                try:
                    date_str = filename[6:16]  # Extract "YYYY-MM-DD" portion
                    if date_str < cutoff_str:
                        logger.info(f"Removing old archive: {filename}")
                        archive_path.unlink()
                        removed_count += 1
                except Exception as e:
                    logger.warning(f"Error parsing archive date from {filename}: {e}")
            
            # Also clean up database entries
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute('''
            DELETE FROM detections
            WHERE ts < ?
            ''', (cutoff_date.isoformat(),))
            
            deleted_rows = cursor.rowcount
            conn.commit()
            conn.close()
            
            logger.info(f"Removed {removed_count} old archives and {deleted_rows} old database entries")
            return removed_count
            
        except Exception as e:
            logger.error(f"Error cleaning up old data: {e}")
            return 0
