"""
TurtleCam Archive Manager
Handles daily archiving and cleanup of motion detection data.
"""

import logging
import shutil
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List
import json

from config import config
from database import db

logger = logging.getLogger(__name__)


class ArchiveManager:
    """Manages archiving and cleanup of turtle detection data"""
    
    def __init__(self):
        self.frames_path = config.get_frames_path()
        self.archives_path = config.get_archives_path()
        self.archives_path.mkdir(parents=True, exist_ok=True)
    
    def archive_date(self, date: datetime) -> bool:
        """Archive all data for a specific date"""
        try:
            date_str = date.strftime("%Y-%m-%d")
            date_dir = self.frames_path / date_str
            
            if not date_dir.exists():
                logger.info(f"No data found for {date_str}")
                return True
            
            # Create archive filename
            archive_name = f"{date_str}.tar.zst"
            archive_path = self.archives_path / archive_name
            
            # Check if archive already exists
            if archive_path.exists():
                logger.info(f"Archive already exists: {archive_name}")
                return True
            
            # Create temporary tar file first
            temp_tar_path = archive_path.with_suffix('.tar')
            
            with tarfile.open(temp_tar_path, 'w') as tar:
                # Add all files from the date directory
                for file_path in date_dir.rglob('*'):
                    if file_path.is_file():
                        # Add with relative path
                        arcname = file_path.relative_to(self.frames_path)
                        tar.add(file_path, arcname=arcname)
            
            # Compress with zstd if available, otherwise use gzip
            try:
                import subprocess
                result = subprocess.run([
                    'zstd', '-q', str(temp_tar_path), '-o', str(archive_path)
                ], capture_output=True)
                
                if result.returncode == 0:
                    temp_tar_path.unlink()  # Remove temporary tar file
                    logger.info(f"Created zstd archive: {archive_name}")
                else:
                    # Fall back to gzip
                    archive_path = archive_path.with_suffix('.tar.gz')
                    with open(temp_tar_path, 'rb') as f_in:
                        import gzip
                        with gzip.open(archive_path, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    temp_tar_path.unlink()
                    logger.info(f"Created gzip archive: {archive_path.name}")
                    
            except (ImportError, FileNotFoundError):
                # zstd not available, use gzip
                archive_path = archive_path.with_suffix('.tar.gz')
                with open(temp_tar_path, 'rb') as f_in:
                    import gzip
                    with gzip.open(archive_path, 'wb') as f_out:
                        shutil.copyfileobj(f_in, f_out)
                temp_tar_path.unlink()
                logger.info(f"Created gzip archive: {archive_path.name}")
            
            # Remove original directory after successful archiving
            shutil.rmtree(date_dir)
            logger.info(f"Archived and removed directory: {date_str}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to archive {date_str}: {e}")
            return False
    
    def cleanup_old_data(self, max_age_days: int = None) -> dict:
        """Clean up old frames and archives"""
        max_age = max_age_days or config.storage.max_age_days
        cutoff_date = datetime.now() - timedelta(days=max_age)
        
        results = {
            'archived_dates': [],
            'removed_archives': [],
            'errors': []
        }
        
        try:
            # Archive recent unarchived dates (but not today)
            yesterday = datetime.now() - timedelta(days=1)
            archive_cutoff = yesterday - timedelta(days=7)  # Archive data older than 7 days
            
            if self.frames_path.exists():
                for date_dir in self.frames_path.iterdir():
                    if not date_dir.is_dir():
                        continue
                    
                    try:
                        date = datetime.strptime(date_dir.name, "%Y-%m-%d")
                        if date < archive_cutoff:
                            if self.archive_date(date):
                                results['archived_dates'].append(date_dir.name)
                            else:
                                results['errors'].append(f"Failed to archive {date_dir.name}")
                    except ValueError:
                        # Not a date directory
                        continue
            
            # Remove old archives
            if self.archives_path.exists():
                for archive_file in self.archives_path.glob("*.tar.*"):
                    try:
                        # Extract date from filename
                        date_str = archive_file.stem.split('.')[0]  # Remove .tar.zst or .tar.gz
                        archive_date = datetime.strptime(date_str, "%Y-%m-%d")
                        
                        if archive_date < cutoff_date:
                            archive_file.unlink()
                            results['removed_archives'].append(archive_file.name)
                            logger.info(f"Removed old archive: {archive_file.name}")
                            
                    except (ValueError, OSError) as e:
                        results['errors'].append(f"Failed to process archive {archive_file.name}: {e}")
            
            # Clean up database records
            db.cleanup_old_records(max_age)
            
            logger.info(f"Cleanup completed: archived {len(results['archived_dates'])} dates, "
                       f"removed {len(results['removed_archives'])} old archives")
            
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def get_archive_stats(self) -> dict:
        """Get statistics about archives"""
        stats = {
            'total_archives': 0,
            'total_size_mb': 0,
            'oldest_archive': None,
            'newest_archive': None,
            'archives_by_month': {}
        }
        
        try:
            if not self.archives_path.exists():
                return stats
            
            archive_files = list(self.archives_path.glob("*.tar.*"))
            stats['total_archives'] = len(archive_files)
            
            if not archive_files:
                return stats
            
            dates = []
            total_size = 0
            
            for archive_file in archive_files:
                try:
                    # Get file size
                    size = archive_file.stat().st_size
                    total_size += size
                    
                    # Extract date
                    date_str = archive_file.stem.split('.')[0]
                    date = datetime.strptime(date_str, "%Y-%m-%d")
                    dates.append(date)
                    
                    # Count by month
                    month_key = date.strftime("%Y-%m")
                    stats['archives_by_month'][month_key] = stats['archives_by_month'].get(month_key, 0) + 1
                    
                except (ValueError, OSError):
                    continue
            
            if dates:
                stats['oldest_archive'] = min(dates).strftime("%Y-%m-%d")
                stats['newest_archive'] = max(dates).strftime("%Y-%m-%d")
            
            stats['total_size_mb'] = round(total_size / (1024 * 1024), 2)
            
        except Exception as e:
            logger.error(f"Failed to get archive stats: {e}")
        
        return stats
    
    def extract_archive(self, archive_name: str, output_dir: Path = None) -> bool:
        """Extract an archive for inspection or recovery"""
        try:
            archive_path = self.archives_path / archive_name
            if not archive_path.exists():
                logger.error(f"Archive not found: {archive_name}")
                return False
            
            output_dir = output_dir or (self.frames_path / "extracted")
            output_dir.mkdir(parents=True, exist_ok=True)
            
            if archive_name.endswith('.tar.zst'):
                # Extract zstd archive
                import subprocess
                result = subprocess.run([
                    'zstd', '-d', str(archive_path), '-c'
                ], capture_output=True)
                
                if result.returncode != 0:
                    logger.error(f"Failed to decompress zstd archive: {result.stderr}")
                    return False
                
                # Extract tar from stdout
                import io
                tar_data = io.BytesIO(result.stdout)
                with tarfile.open(fileobj=tar_data, mode='r') as tar:
                    tar.extractall(output_dir)
                    
            elif archive_name.endswith('.tar.gz'):
                # Extract gzip archive
                with tarfile.open(archive_path, 'r:gz') as tar:
                    tar.extractall(output_dir)
            else:
                logger.error(f"Unsupported archive format: {archive_name}")
                return False
            
            logger.info(f"Extracted archive {archive_name} to {output_dir}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to extract archive {archive_name}: {e}")
            return False


def main():
    """Main entry point for archive management"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="TurtleCam Archive Manager")
    parser.add_argument("--cleanup", action="store_true", help="Run cleanup of old data")
    parser.add_argument("--archive-date", type=str, help="Archive specific date (YYYY-MM-DD)")
    parser.add_argument("--stats", action="store_true", help="Show archive statistics")
    parser.add_argument("--extract", type=str, help="Extract specific archive")
    parser.add_argument("--max-age", type=int, help="Maximum age in days for cleanup")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, config.system.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    manager = ArchiveManager()
    
    try:
        if args.cleanup:
            results = manager.cleanup_old_data(args.max_age)
            print(f"Cleanup results: {json.dumps(results, indent=2)}")
            
        elif args.archive_date:
            date = datetime.strptime(args.archive_date, "%Y-%m-%d")
            success = manager.archive_date(date)
            print(f"Archive {'successful' if success else 'failed'}")
            
        elif args.stats:
            stats = manager.get_archive_stats()
            print(f"Archive statistics: {json.dumps(stats, indent=2)}")
            
        elif args.extract:
            success = manager.extract_archive(args.extract)
            print(f"Extraction {'successful' if success else 'failed'}")
            
        else:
            parser.print_help()
            
    except Exception as e:
        logger.error(f"Archive manager error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
