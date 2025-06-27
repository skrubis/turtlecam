"""Storage management module for TurtleCam.

This module manages storage resources, handling auto-deletion and compression
of old data to ensure efficient disk space usage.
"""

import os
import logging
import shutil
import time
import zipfile
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple

# Try to import tqdm for progress reporting
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

logger = logging.getLogger(__name__)


class StorageManager:
    """Manages TurtleCam storage resources."""
    
    def __init__(self, 
                 data_store,
                 retention_days: int = 30,
                 max_usage_pct: float = 85.0,
                 cleanup_threshold_pct: float = 80.0,
                 target_usage_pct: float = 70.0,
                 compress_older_than_days: int = 7):
        """Initialize storage manager.
        
        Args:
            data_store: DataStore instance
            retention_days (int): Days to retain data before archiving
            max_usage_pct (float): Maximum acceptable disk usage percentage
            cleanup_threshold_pct (float): Disk usage percentage to trigger cleanup
            target_usage_pct (float): Target disk usage after cleanup
            compress_older_than_days (int): Days before compressing data
        """
        self.data_store = data_store
        self.retention_days = retention_days
        self.max_usage_pct = max_usage_pct
        self.cleanup_threshold_pct = cleanup_threshold_pct
        self.target_usage_pct = target_usage_pct
        self.compress_older_than_days = compress_older_than_days
        
        # Base paths
        self.base_path = self.data_store.base_path
        self.image_path = self.data_store.image_path
        self.archive_path = self.data_store.archive_path
        
    def check_storage_status(self):
        """Check current storage status.
        
        Returns:
            dict: Storage status information
        """
        try:
            # Check disk usage
            disk_usage = shutil.disk_usage(self.base_path)
            usage_pct = disk_usage.used / disk_usage.total * 100
            
            # Count files
            image_files = self._count_files(self.image_path)
            archive_files = self._count_files(self.archive_path)
            
            # Get database size
            db_size = Path(self.data_store.db_path).stat().st_size if Path(self.data_store.db_path).exists() else 0
            
            # Calculate space used by images
            images_size = self._calculate_dir_size(self.image_path)
            archive_size = self._calculate_dir_size(self.archive_path)
            
            status = {
                "timestamp": datetime.now().isoformat(),
                "total_bytes": disk_usage.total,
                "used_bytes": disk_usage.used,
                "free_bytes": disk_usage.free,
                "usage_pct": usage_pct,
                "image_files": image_files,
                "archive_files": archive_files,
                "database_size_bytes": db_size,
                "images_size_bytes": images_size,
                "archive_size_bytes": archive_size,
                "needs_cleanup": usage_pct > self.cleanup_threshold_pct
            }
            
            return status
            
        except Exception as e:
            logger.error(f"Error checking storage status: {e}")
            return {"error": str(e)}
    
    def _count_files(self, directory_path):
        """Count files in directory and subdirectories.
        
        Args:
            directory_path (Path): Directory to count
            
        Returns:
            int: File count
        """
        count = 0
        try:
            for path in Path(directory_path).rglob('*'):
                if path.is_file():
                    count += 1
        except Exception as e:
            logger.error(f"Error counting files in {directory_path}: {e}")
            
        return count
    
    def _calculate_dir_size(self, directory_path):
        """Calculate total size of directory and subdirectories.
        
        Args:
            directory_path (Path): Directory to measure
            
        Returns:
            int: Total size in bytes
        """
        total_size = 0
        try:
            for path in Path(directory_path).rglob('*'):
                if path.is_file():
                    total_size += path.stat().st_size
        except Exception as e:
            logger.error(f"Error calculating size of {directory_path}: {e}")
            
        return total_size
    
    def perform_maintenance(self, force=False):
        """Perform storage maintenance tasks.
        
        Args:
            force (bool): Force maintenance regardless of thresholds
            
        Returns:
            dict: Maintenance results
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "tasks_performed": []
        }
        
        try:
            # Check storage status
            status = self.check_storage_status()
            results["initial_status"] = status
            
            # Archive old data
            if force or status.get("usage_pct", 0) > self.cleanup_threshold_pct:
                # Archive first
                archive_results = self.archive_old_data()
                results["archive_results"] = archive_results
                results["tasks_performed"].append("archive")
                
                # Then compress
                compress_results = self.compress_archived_data()
                results["compress_results"] = compress_results
                results["tasks_performed"].append("compress")
                
                # Then cleanup if still needed
                if force or status.get("usage_pct", 0) > self.cleanup_threshold_pct:
                    cleanup_results = self.cleanup_disk_space()
                    results["cleanup_results"] = cleanup_results
                    results["tasks_performed"].append("cleanup")
                    
            # Check final status
            final_status = self.check_storage_status()
            results["final_status"] = final_status
            
            # Log maintenance summary
            tasks = ", ".join(results["tasks_performed"]) if results["tasks_performed"] else "none"
            before = status.get("usage_pct", 0)
            after = final_status.get("usage_pct", 0)
            logger.info(f"Storage maintenance completed: tasks={tasks}, "
                      f"usage {before:.1f}% -> {after:.1f}%")
                      
            return results
            
        except Exception as e:
            logger.error(f"Error performing maintenance: {e}")
            results["error"] = str(e)
            return results
    
    def archive_old_data(self):
        """Archive data older than retention threshold.
        
        Returns:
            dict: Archive statistics
        """
        # Use data store's archive method
        return self.data_store.archive_old_data(days_threshold=self.retention_days)
    
    def compress_archived_data(self):
        """Compress archived data to save space.
        
        Returns:
            dict: Compression statistics
        """
        stats = {
            "timestamp": datetime.now().isoformat(),
            "directories_compressed": 0,
            "files_compressed": 0,
            "bytes_before": 0,
            "bytes_after": 0
        }
        
        try:
            # Get archive subdirectories
            archive_dirs = [d for d in self.archive_path.iterdir() if d.is_dir()]
            
            # Filter for directories older than compress threshold
            compress_cutoff = datetime.now() - timedelta(days=self.compress_older_than_days)
            dirs_to_compress = []
            
            for dir_path in archive_dirs:
                try:
                    # Try to parse directory name as date
                    if '-' in dir_path.name:
                        dir_date = datetime.strptime(dir_path.name, '%Y-%m')
                        if dir_date < compress_cutoff:
                            dirs_to_compress.append(dir_path)
                except ValueError:
                    # If dir name isn't a date format, check modification time
                    try:
                        if datetime.fromtimestamp(dir_path.stat().st_mtime) < compress_cutoff:
                            dirs_to_compress.append(dir_path)
                    except Exception:
                        logger.warning(f"Could not determine age of {dir_path}")
            
            # Process each directory
            for dir_path in dirs_to_compress:
                # Check if there's a zip file already
                zip_path = Path(f"{dir_path}.zip")
                if zip_path.exists():
                    logger.debug(f"Skipping already compressed directory: {dir_path}")
                    continue
                    
                # Get list of files
                files = [f for f in dir_path.rglob('*') if f.is_file()]
                
                # Skip empty directories
                if not files:
                    logger.debug(f"Skipping empty directory: {dir_path}")
                    continue
                
                # Calculate total size before compression
                dir_size_before = sum(f.stat().st_size for f in files)
                stats["bytes_before"] += dir_size_before
                
                # Create zip file
                logger.info(f"Compressing directory: {dir_path} ({len(files)} files)")
                
                # Use progress bar if available
                if TQDM_AVAILABLE:
                    files_iter = tqdm(files, desc=f"Compressing {dir_path.name}")
                else:
                    files_iter = files
                
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file_path in files_iter:
                        # Add file to zip with relative path
                        arcname = file_path.relative_to(dir_path)
                        zipf.write(file_path, arcname)
                
                # Get zip file size
                zip_size = zip_path.stat().st_size
                stats["bytes_after"] += zip_size
                
                # Update stats
                stats["directories_compressed"] += 1
                stats["files_compressed"] += len(files)
                
                # Delete the original directory if zip was created successfully
                if zip_path.exists():
                    logger.info(f"Removing original directory: {dir_path} (compressed size: {zip_size / 1024:.1f} KB)")
                    shutil.rmtree(dir_path)
                
            # Log compression summary
            compression_ratio = stats["bytes_after"] / stats["bytes_before"] if stats["bytes_before"] > 0 else 1.0
            saved_mb = (stats["bytes_before"] - stats["bytes_after"]) / (1024 * 1024)
            
            logger.info(f"Compressed {stats['directories_compressed']} directories, "
                      f"{stats['files_compressed']} files, saved {saved_mb:.1f} MB "
                      f"(ratio: {compression_ratio:.2f})")
                      
            return stats
            
        except Exception as e:
            logger.error(f"Error compressing archived data: {e}")
            stats["error"] = str(e)
            return stats
    
    def cleanup_disk_space(self):
        """Clean up disk space when usage exceeds threshold.
        
        Returns:
            dict: Cleanup statistics
        """
        # Use data store's cleanup method with our target
        return self.data_store.cleanup_disk_space(target_usage_pct=self.target_usage_pct)
    
    def vacuum_database(self):
        """Vacuum SQLite database to reclaim space.
        
        Returns:
            dict: Operation results
        """
        results = {
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            # Get initial size
            db_path = self.data_store.db_path
            initial_size = Path(db_path).stat().st_size
            results["initial_size_bytes"] = initial_size
            
            # Connect and vacuum
            conn = sqlite3.connect(db_path)
            logger.info(f"Vacuuming database: {db_path}")
            conn.execute("VACUUM")
            conn.close()
            
            # Get final size
            final_size = Path(db_path).stat().st_size
            results["final_size_bytes"] = final_size
            results["bytes_saved"] = initial_size - final_size
            
            logger.info(f"Database vacuum complete: {initial_size/1024:.1f} KB -> {final_size/1024:.1f} KB "
                      f"(saved {results['bytes_saved']/1024:.1f} KB)")
            return results
            
        except Exception as e:
            logger.error(f"Error vacuuming database: {e}")
            results["error"] = str(e)
            return results
    
    def export_data_for_ml(self, export_path=None, start_date=None, end_date=None,
                         format='yolo', limit=None, labels=None):
        """Export data for machine learning.
        
        Args:
            export_path (str, optional): Path to export directory
            start_date (datetime, optional): Start date for export range
            end_date (datetime, optional): End date for export range
            format (str): Export format ('yolo' or 'tensorflow')
            limit (int, optional): Maximum crops to export
            labels (list, optional): Labels to filter by
            
        Returns:
            dict: Export statistics
        """
        # This is a placeholder for the actual ML export functionality
        # The full implementation would be in export_yolo.py
        results = {
            "timestamp": datetime.now().isoformat(),
            "format": format,
            "message": "Export functionality will be implemented in export_yolo.py"
        }
        
        return results
