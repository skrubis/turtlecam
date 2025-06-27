#!/usr/bin/env python3
"""
Soak Test Monitor for TurtleCam

This script monitors system resources during a soak test and records metrics
to help identify potential issues like memory leaks, CPU spikes, or storage problems.

Usage:
    python soak_test_monitor.py --interval 300 --output soak_test_results.csv
"""

import argparse
import time
import datetime
import os
import csv
import subprocess
import sqlite3
import logging
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('soak_test_monitor.log')
    ]
)
logger = logging.getLogger('soak_test_monitor')


class SoakTestMonitor:
    """Monitors system resources during a soak test."""
    
    def __init__(self, interval=300, output_file="soak_test_results.csv", 
                 db_path="data/turtlecam.db", max_duration_hours=None):
        """Initialize the soak test monitor.
        
        Args:
            interval (int): Seconds between measurements
            output_file (str): CSV file to store results
            db_path (str): Path to TurtleCam database
            max_duration_hours (int, optional): Maximum test duration in hours
        """
        self.interval = interval
        self.output_file = output_file
        self.db_path = Path(db_path)
        self.max_duration = max_duration_hours * 3600 if max_duration_hours else None
        self.start_time = time.time()
        self.running = False
        
        # Check if output file exists
        file_exists = os.path.isfile(self.output_file)
        
        # Initialize CSV file
        self.csv_fields = [
            'timestamp', 'uptime_hours', 'cpu_percent', 'memory_used_mb',
            'memory_free_mb', 'disk_usage_percent', 'system_temp_c',
            'db_size_mb', 'motion_events_count', 'crops_count', 
            'env_logs_count', 'relay_logs_count'
        ]
        
        with open(self.output_file, mode='a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.csv_fields)
            if not file_exists:
                writer.writeheader()
    
    def start(self):
        """Start the monitoring process."""
        logger.info(f"Starting soak test monitoring, interval: {self.interval}s")
        logger.info(f"Results will be saved to: {self.output_file}")
        
        self.running = True
        self.start_time = time.time()
        
        try:
            while self.running:
                # Collect and record metrics
                self.record_metrics()
                
                # Check if we've reached the maximum duration
                if self.max_duration and (time.time() - self.start_time > self.max_duration):
                    logger.info(f"Maximum test duration reached ({self.max_duration/3600} hours)")
                    self.running = False
                    break
                
                # Sleep until next collection
                time.sleep(self.interval)
                
        except KeyboardInterrupt:
            logger.info("Monitoring stopped by user")
        except Exception as e:
            logger.error(f"Error during monitoring: {e}")
        finally:
            logger.info("Monitoring completed")
    
    def record_metrics(self):
        """Collect and record system metrics."""
        metrics = self.collect_metrics()
        
        # Write to CSV file
        with open(self.output_file, mode='a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.csv_fields)
            writer.writerow(metrics)
        
        # Log a summary
        logger.info(f"Recorded metrics - CPU: {metrics['cpu_percent']}%, "
                   f"Memory: {metrics['memory_used_mb']}/{metrics['memory_used_mb'] + metrics['memory_free_mb']} MB, "
                   f"Disk: {metrics['disk_usage_percent']}%, "
                   f"Temp: {metrics['system_temp_c']}°C")
    
    def collect_metrics(self):
        """Collect system metrics.
        
        Returns:
            dict: System metrics
        """
        now = datetime.datetime.now()
        uptime_hours = (time.time() - self.start_time) / 3600
        
        # Basic system metrics
        metrics = {
            'timestamp': now.isoformat(),
            'uptime_hours': round(uptime_hours, 2)
        }
        
        # CPU usage
        try:
            cpu_percent = self._get_cpu_percent()
            metrics['cpu_percent'] = cpu_percent
        except Exception as e:
            logger.error(f"Failed to get CPU usage: {e}")
            metrics['cpu_percent'] = -1
        
        # Memory usage
        try:
            memory_used, memory_free = self._get_memory_usage()
            metrics['memory_used_mb'] = memory_used
            metrics['memory_free_mb'] = memory_free
        except Exception as e:
            logger.error(f"Failed to get memory usage: {e}")
            metrics['memory_used_mb'] = -1
            metrics['memory_free_mb'] = -1
        
        # Disk usage
        try:
            disk_percent = self._get_disk_usage()
            metrics['disk_usage_percent'] = disk_percent
        except Exception as e:
            logger.error(f"Failed to get disk usage: {e}")
            metrics['disk_usage_percent'] = -1
        
        # System temperature (Raspberry Pi)
        try:
            temp_c = self._get_system_temp()
            metrics['system_temp_c'] = temp_c
        except Exception as e:
            logger.error(f"Failed to get system temperature: {e}")
            metrics['system_temp_c'] = -1
        
        # Database metrics
        try:
            db_metrics = self._get_db_metrics()
            metrics.update(db_metrics)
        except Exception as e:
            logger.error(f"Failed to get database metrics: {e}")
            metrics['db_size_mb'] = -1
            metrics['motion_events_count'] = -1
            metrics['crops_count'] = -1
            metrics['env_logs_count'] = -1
            metrics['relay_logs_count'] = -1
        
        return metrics
    
    def _get_cpu_percent(self):
        """Get CPU usage percentage.
        
        Returns:
            float: CPU usage percentage
        """
        # Use 'top' command to get CPU usage
        cmd = "top -bn1 | grep 'Cpu(s)' | awk '{print $2 + $4}'"
        output = subprocess.check_output(cmd, shell=True, text=True)
        return float(output.strip())
    
    def _get_memory_usage(self):
        """Get memory usage.
        
        Returns:
            tuple: (used_mb, free_mb)
        """
        # Use 'free' command to get memory usage
        cmd = "free -m | grep Mem | awk '{print $3, $4}'"
        output = subprocess.check_output(cmd, shell=True, text=True)
        used, free = map(int, output.strip().split())
        return used, free
    
    def _get_disk_usage(self):
        """Get disk usage percentage.
        
        Returns:
            float: Disk usage percentage
        """
        # Use 'df' command to get disk usage
        cmd = "df -h / | tail -1 | awk '{print $5}' | sed 's/%//'"
        output = subprocess.check_output(cmd, shell=True, text=True)
        return float(output.strip())
    
    def _get_system_temp(self):
        """Get system temperature (Raspberry Pi).
        
        Returns:
            float: System temperature in Celsius
        """
        try:
            # Try vcgencmd for Raspberry Pi
            cmd = "vcgencmd measure_temp | cut -d= -f2 | cut -d\\' -f1"
            output = subprocess.check_output(cmd, shell=True, text=True)
            return float(output.strip())
        except:
            # Try reading from thermal zone on other Linux systems
            if os.path.exists('/sys/class/thermal/thermal_zone0/temp'):
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    temp = int(f.read().strip()) / 1000.0
                return temp
            else:
                return -1  # Temperature not available
    
    def _get_db_metrics(self):
        """Get database metrics.
        
        Returns:
            dict: Database metrics
        """
        result = {}
        
        # Check if database exists
        if not self.db_path.exists():
            return {
                'db_size_mb': 0,
                'motion_events_count': 0,
                'crops_count': 0,
                'env_logs_count': 0,
                'relay_logs_count': 0
            }
        
        # Get database size
        db_size_mb = os.path.getsize(self.db_path) / (1024 * 1024)
        result['db_size_mb'] = round(db_size_mb, 2)
        
        # Connect to database and get table counts
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Get counts for key tables
            tables = ['motion_events', 'crops', 'env_logs', 'relay_logs']
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    count = cursor.fetchone()[0]
                    result[f'{table}_count'] = count
                except sqlite3.Error:
                    result[f'{table}_count'] = -1
            
            conn.close()
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            for table in tables:
                result[f'{table}_count'] = -1
        
        return result


def main():
    parser = argparse.ArgumentParser(description="TurtleCam Soak Test Monitor")
    parser.add_argument('-i', '--interval', type=int, default=300,
                        help='Sampling interval in seconds (default: 300)')
    parser.add_argument('-o', '--output', type=str, default='soak_test_results.csv',
                        help='Output CSV file (default: soak_test_results.csv)')
    parser.add_argument('-d', '--db', type=str, default='data/turtlecam.db',
                        help='Path to TurtleCam database (default: data/turtlecam.db)')
    parser.add_argument('-t', '--time', type=int,
                        help='Maximum test duration in hours (default: unlimited)')
    
    args = parser.parse_args()
    
    monitor = SoakTestMonitor(
        interval=args.interval,
        output_file=args.output,
        db_path=args.db,
        max_duration_hours=args.time
    )
    
    monitor.start()


if __name__ == "__main__":
    main()
