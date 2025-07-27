"""
TurtleCam Database Management
SQLite database for storing detection events and metadata.
"""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from dataclasses import dataclass

from config import config

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """Detection event data structure"""
    timestamp: datetime
    bbox_x: int
    bbox_y: int
    bbox_w: int
    bbox_h: int
    confidence: float = 1.0
    img_path: Optional[str] = None


class DatabaseManager:
    """Manages SQLite database operations for turtle detections"""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.get_database_path()
        self._ensure_database()
    
    def _ensure_database(self):
        """Create database and tables if they don't exist"""
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS detections (
                    ts DATETIME PRIMARY KEY,
                    bbox_x INTEGER NOT NULL,
                    bbox_y INTEGER NOT NULL,
                    bbox_w INTEGER NOT NULL,
                    bbox_h INTEGER NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    img_path TEXT
                )
            """)
            
            # Create index for faster queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_detections_ts 
                ON detections(ts)
            """)
            
            conn.commit()
            logger.info(f"Database initialized at {self.db_path}")
    
    def insert_detection(self, detection: Detection) -> bool:
        """Insert a new detection record"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO detections 
                    (ts, bbox_x, bbox_y, bbox_w, bbox_h, confidence, img_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    detection.timestamp,
                    detection.bbox_x,
                    detection.bbox_y,
                    detection.bbox_w,
                    detection.bbox_h,
                    detection.confidence,
                    detection.img_path
                ))
                conn.commit()
                logger.debug(f"Inserted detection at {detection.timestamp}")
                return True
        except sqlite3.Error as e:
            logger.error(f"Failed to insert detection: {e}")
            return False
    
    def get_detections_by_date(self, date: datetime) -> List[Detection]:
        """Get all detections for a specific date"""
        start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT ts, bbox_x, bbox_y, bbox_w, bbox_h, confidence, img_path
                    FROM detections
                    WHERE ts >= ? AND ts < ?
                    ORDER BY ts
                """, (start_date, end_date))
                
                detections = []
                for row in cursor.fetchall():
                    detections.append(Detection(
                        timestamp=datetime.fromisoformat(row[0]),
                        bbox_x=row[1],
                        bbox_y=row[2],
                        bbox_w=row[3],
                        bbox_h=row[4],
                        confidence=row[5],
                        img_path=row[6]
                    ))
                
                return detections
        except sqlite3.Error as e:
            logger.error(f"Failed to get detections by date: {e}")
            return []
    
    def get_recent_detections(self, limit: int = 10) -> List[Detection]:
        """Get the most recent detections"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT ts, bbox_x, bbox_y, bbox_w, bbox_h, confidence, img_path
                    FROM detections
                    ORDER BY ts DESC
                    LIMIT ?
                """, (limit,))
                
                detections = []
                for row in cursor.fetchall():
                    detections.append(Detection(
                        timestamp=datetime.fromisoformat(row[0]),
                        bbox_x=row[1],
                        bbox_y=row[2],
                        bbox_w=row[3],
                        bbox_h=row[4],
                        confidence=row[5],
                        img_path=row[6]
                    ))
                
                return detections
        except sqlite3.Error as e:
            logger.error(f"Failed to get recent detections: {e}")
            return []
    
    def cleanup_old_records(self, max_age_days: int = None) -> int:
        """Remove detection records older than max_age_days"""
        max_age = max_age_days or config.storage.max_age_days
        cutoff_date = datetime.now() - timedelta(days=max_age)
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM detections
                    WHERE ts < ?
                """, (cutoff_date,))
                
                deleted_count = cursor.rowcount
                conn.commit()
                
                if deleted_count > 0:
                    logger.info(f"Cleaned up {deleted_count} old detection records")
                
                return deleted_count
        except sqlite3.Error as e:
            logger.error(f"Failed to cleanup old records: {e}")
            return 0
    
    def get_stats(self) -> dict:
        """Get database statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Total detections
                cursor = conn.execute("SELECT COUNT(*) FROM detections")
                total_detections = cursor.fetchone()[0]
                
                # Detections today
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM detections 
                    WHERE ts >= ?
                """, (today,))
                today_detections = cursor.fetchone()[0]
                
                # Date range
                cursor = conn.execute("""
                    SELECT MIN(ts), MAX(ts) FROM detections
                """)
                date_range = cursor.fetchone()
                
                return {
                    "total_detections": total_detections,
                    "today_detections": today_detections,
                    "first_detection": date_range[0],
                    "last_detection": date_range[1]
                }
        except sqlite3.Error as e:
            logger.error(f"Failed to get stats: {e}")
            return {}


# Global database instance
db = DatabaseManager()
