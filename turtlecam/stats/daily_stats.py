#!/usr/bin/env python3
"""
Daily Statistics Reporter for TurtleCam

This module provides functionality to generate and report daily statistics about:
- Movement activity (count, duration, patterns)
- Environmental conditions (temperature, humidity)
- Comparative analysis with historical data
"""

import os
import logging
import sqlite3
import datetime
from pathlib import Path
import json
import statistics
from collections import defaultdict
import matplotlib.pyplot as plt
import numpy as np
import csv
import telegram
from ..config.yaml_config import load_yaml_config

logger = logging.getLogger(__name__)


class DailyStatsReporter:
    """
    Generates daily statistics reports for turtle activity and environmental conditions.
    
    Features:
    - Daily movement activity summary
    - Temperature and humidity trends
    - Comparative analysis with previous day and week
    - Optional data visualization
    - Export to various formats (JSON, CSV, etc.)
    - Integration with Telegram notifications
    """
    
    def __init__(self, db_path, output_dir="data/stats", config=None):
        """
        Initialize the daily stats reporter.
        
        Args:
            db_path (str): Path to the SQLite database
            output_dir (str): Directory to save reports and visualizations
            config (dict, optional): Configuration options
        """
        self.db_path = Path(db_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Default configuration
        self.config = {
            'active_hours_start': 8,  # 8:00 AM
            'active_hours_end': 20,   # 8:00 PM
            'movement_threshold': 3,  # Min events to be considered active
            'report_time': "23:59",   # When to generate daily report
            'include_charts': True,   # Generate charts with reports
            'telegram_notifications': True,  # Send report summary via Telegram
            'keep_reports_days': 90,  # How long to keep reports
        }
        
        # Update with user config if provided
        if config:
            self.config.update(config)
    
    def generate_daily_report(self, target_date=None):
        """
        Generate a complete daily statistics report.
        
        Args:
            target_date (datetime.date, optional): Date to generate report for, 
                                                  defaults to yesterday
        
        Returns:
            dict: Report data
        """
        if target_date is None:
            # Default to yesterday to ensure complete data
            target_date = datetime.date.today() - datetime.timedelta(days=1)
        
        # Ensure we have a date object
        if isinstance(target_date, datetime.datetime):
            target_date = target_date.date()
        
        logger.info(f"Generating daily report for {target_date}")
        
        # Prepare report structure
        report = {
            'date': target_date.isoformat(),
            'generated_at': datetime.datetime.now().isoformat(),
            'movement': self._get_movement_stats(target_date),
            'environment': self._get_environment_stats(target_date),
            'comparisons': {
                'previous_day': self._get_comparison_stats(target_date, 1),
                'previous_week': self._get_comparison_stats(target_date, 7),
                'weekly_avg': self._get_weekly_average(target_date),
            }
        }
        
        # Save report
        self._save_report(report, target_date)
        
        # Generate visualizations if enabled
        if self.config['include_charts']:
            self._generate_charts(report, target_date)
        
        return report
    
    def _get_movement_stats(self, target_date):
        """
        Get statistics about movement activity for the specified date.
        
        Args:
            target_date (datetime.date): Date to analyze
            
        Returns:
            dict: Movement statistics
        """
        start_timestamp = datetime.datetime.combine(
            target_date, datetime.time.min).timestamp()
        end_timestamp = datetime.datetime.combine(
            target_date, datetime.time.max).timestamp()
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Total movement events
            cursor.execute(
                """SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
                   FROM motion_events
                   WHERE timestamp >= ? AND timestamp <= ?""", 
                (start_timestamp, end_timestamp)
            )
            count, first_event, last_event = cursor.fetchone()
            
            # No movement detected on this day
            if count == 0:
                return {
                    'total_events': 0,
                    'active_hours': [],
                    'peak_hour': None,
                    'morning_activity': 0,
                    'afternoon_activity': 0,
                    'evening_activity': 0,
                    'night_activity': 0,
                    'hourly_distribution': [0] * 24,
                }
            
            # Hourly distribution
            cursor.execute(
                """SELECT CAST(strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')) AS INTEGER) as hour,
                          COUNT(*) as event_count
                   FROM motion_events
                   WHERE timestamp >= ? AND timestamp <= ?
                   GROUP BY hour
                   ORDER BY hour""",
                (start_timestamp, end_timestamp)
            )
            
            hourly_data = cursor.fetchall()
            hourly_distribution = [0] * 24
            
            for hour, count in hourly_data:
                hourly_distribution[hour] = count
            
            # Find peak activity hour
            peak_hour = hourly_distribution.index(max(hourly_distribution))
            
            # Calculate time-of-day activity percentages
            morning_events = sum(hourly_distribution[6:12])  # 6 AM - 12 PM
            afternoon_events = sum(hourly_distribution[12:18])  # 12 PM - 6 PM
            evening_events = sum(hourly_distribution[18:22])  # 6 PM - 10 PM
            night_events = sum(hourly_distribution[22:] + hourly_distribution[:6])  # 10 PM - 6 AM
            total = sum(hourly_distribution)
            
            # Active hours (hours with activity above threshold)
            active_hours = [hour for hour, count in enumerate(hourly_distribution) 
                          if count >= self.config['movement_threshold']]
            
            conn.close()
            
            return {
                'total_events': total,
                'active_hours': active_hours,
                'peak_hour': peak_hour,
                'morning_activity': round(morning_events / total * 100 if total > 0 else 0, 1),
                'afternoon_activity': round(afternoon_events / total * 100 if total > 0 else 0, 1),
                'evening_activity': round(evening_events / total * 100 if total > 0 else 0, 1),
                'night_activity': round(night_events / total * 100 if total > 0 else 0, 1),
                'hourly_distribution': hourly_distribution,
            }
            
        except sqlite3.Error as e:
            logger.error(f"Database error retrieving movement stats: {e}")
            return {
                'error': str(e),
                'total_events': 0,
                'hourly_distribution': [0] * 24
            }
    
    def _get_environment_stats(self, target_date):
        """
        Get statistics about environmental conditions for the specified date.
        
        Args:
            target_date (datetime.date): Date to analyze
            
        Returns:
            dict: Environmental statistics
        """
        start_timestamp = datetime.datetime.combine(
            target_date, datetime.time.min).timestamp()
        end_timestamp = datetime.datetime.combine(
            target_date, datetime.time.max).timestamp()
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Temperature stats
            cursor.execute(
                """SELECT AVG(temperature), MIN(temperature), MAX(temperature),
                          COUNT(*), stddev(temperature)
                   FROM env_logs
                   WHERE timestamp >= ? AND timestamp <= ?""", 
                (start_timestamp, end_timestamp)
            )
            avg_temp, min_temp, max_temp, temp_count, temp_stddev = cursor.fetchone()
            
            # Humidity stats
            cursor.execute(
                """SELECT AVG(humidity), MIN(humidity), MAX(humidity),
                          COUNT(*), stddev(humidity)
                   FROM env_logs
                   WHERE timestamp >= ? AND timestamp <= ?""", 
                (start_timestamp, end_timestamp)
            )
            avg_humid, min_humid, max_humid, humid_count, humid_stddev = cursor.fetchone()
            
            # Check if we have any data
            if not temp_count:
                return {
                    'temperature': {'count': 0},
                    'humidity': {'count': 0}
                }
            
            # Hourly averages
            cursor.execute(
                """SELECT CAST(strftime('%H', datetime(timestamp, 'unixepoch', 'localtime')) AS INTEGER) as hour,
                          AVG(temperature) as avg_temp,
                          AVG(humidity) as avg_humid
                   FROM env_logs
                   WHERE timestamp >= ? AND timestamp <= ?
                   GROUP BY hour
                   ORDER BY hour""",
                (start_timestamp, end_timestamp)
            )
            
            hourly_data = cursor.fetchall()
            hourly_temp = [None] * 24
            hourly_humid = [None] * 24
            
            for hour, temp, humid in hourly_data:
                hourly_temp[hour] = round(temp, 1) if temp is not None else None
                hourly_humid[hour] = round(humid, 1) if humid is not None else None
            
            conn.close()
            
            return {
                'temperature': {
                    'count': temp_count,
                    'avg': round(avg_temp, 1) if avg_temp is not None else None,
                    'min': round(min_temp, 1) if min_temp is not None else None,
                    'max': round(max_temp, 1) if max_temp is not None else None,
                    'stddev': round(temp_stddev, 2) if temp_stddev is not None else None,
                    'hourly': hourly_temp,
                },
                'humidity': {
                    'count': humid_count,
                    'avg': round(avg_humid, 1) if avg_humid is not None else None,
                    'min': round(min_humid, 1) if min_humid is not None else None,
                    'max': round(max_humid, 1) if max_humid is not None else None,
                    'stddev': round(humid_stddev, 2) if humid_stddev is not None else None,
                    'hourly': hourly_humid,
                }
            }
            
        except sqlite3.Error as e:
            logger.error(f"Database error retrieving environment stats: {e}")
            return {
                'error': str(e),
                'temperature': {'count': 0},
                'humidity': {'count': 0}
            }
    
    def _get_comparison_stats(self, target_date, days_ago=1):
        """
        Get comparative statistics between target date and a previous date.
        
        Args:
            target_date (datetime.date): Target date for comparison
            days_ago (int): Number of days to look back for comparison
            
        Returns:
            dict: Comparison statistics
        """
        compare_date = target_date - datetime.timedelta(days=days_ago)
        
        # Get stats for both dates
        target_movement = self._get_movement_stats(target_date)
        target_env = self._get_environment_stats(target_date)
        compare_movement = self._get_movement_stats(compare_date)
        compare_env = self._get_environment_stats(compare_date)
        
        # Calculate differences
        movement_diff = target_movement['total_events'] - compare_movement['total_events']
        movement_pct_change = ((target_movement['total_events'] / max(1, compare_movement['total_events'])) - 1) * 100
        
        # Temperature comparison
        if target_env['temperature']['count'] > 0 and compare_env['temperature']['count'] > 0:
            temp_diff = target_env['temperature']['avg'] - compare_env['temperature']['avg']
            temp_max_diff = target_env['temperature']['max'] - compare_env['temperature']['max']
            temp_min_diff = target_env['temperature']['min'] - compare_env['temperature']['min']
        else:
            temp_diff = temp_max_diff = temp_min_diff = 0
        
        # Humidity comparison
        if target_env['humidity']['count'] > 0 and compare_env['humidity']['count'] > 0:
            humid_diff = target_env['humidity']['avg'] - compare_env['humidity']['avg']
            humid_max_diff = target_env['humidity']['max'] - compare_env['humidity']['max']
            humid_min_diff = target_env['humidity']['min'] - compare_env['humidity']['min']
        else:
            humid_diff = humid_max_diff = humid_min_diff = 0
        
        # Day to day shift in activity pattern (hourly correlation)
        activity_pattern_shift = self._calculate_activity_shift(
            target_movement['hourly_distribution'],
            compare_movement['hourly_distribution']
        )
        
        return {
            'date': compare_date.isoformat(),
            'movement': {
                'difference': movement_diff,
                'percent_change': round(movement_pct_change, 1),
                'pattern_shift': activity_pattern_shift,
            },
            'temperature': {
                'avg_diff': round(temp_diff, 1),
                'max_diff': round(temp_max_diff, 1),
                'min_diff': round(temp_min_diff, 1),
            },
            'humidity': {
                'avg_diff': round(humid_diff, 1),
                'max_diff': round(humid_max_diff, 1),
                'min_diff': round(humid_min_diff, 1),
            },
        }
    
    def _get_weekly_average(self, target_date):
        """
        Calculate weekly averages leading up to the target date.
        
        Args:
            target_date (datetime.date): End date for weekly average
            
        Returns:
            dict: Weekly average statistics
        """
        # Calculate date range (last 7 days not including target date)
        start_date = target_date - datetime.timedelta(days=7)
        end_date = target_date - datetime.timedelta(days=1)
        
        # Movement stats aggregation
        total_movement = 0
        hourly_totals = [0] * 24
        days_with_data = 0
        
        # Temperature and humidity aggregation
        temp_values = []
        temp_min_values = []
        temp_max_values = []
        humid_values = []
        humid_min_values = []
        humid_max_values = []
        
        # Collect data for each day
        current_date = start_date
        while current_date <= end_date:
            # Movement data
            day_movement = self._get_movement_stats(current_date)
            if day_movement['total_events'] > 0:
                days_with_data += 1
                total_movement += day_movement['total_events']
                
                # Add hourly distributions
                for hour, count in enumerate(day_movement['hourly_distribution']):
                    hourly_totals[hour] += count
            
            # Environmental data
            day_env = self._get_environment_stats(current_date)
            if day_env['temperature']['count'] > 0:
                temp_values.append(day_env['temperature']['avg'])
                temp_min_values.append(day_env['temperature']['min'])
                temp_max_values.append(day_env['temperature']['max'])
                
                humid_values.append(day_env['humidity']['avg'])
                humid_min_values.append(day_env['humidity']['min'])
                humid_max_values.append(day_env['humidity']['max'])
            
            current_date += datetime.timedelta(days=1)
        
        # Calculate averages
        avg_movement = total_movement / max(1, days_with_data)
        avg_hourly = [round(count / max(1, days_with_data), 1) for count in hourly_totals]
        
        # Calculate environmental averages
        if temp_values:
            avg_temp = sum(temp_values) / len(temp_values)
            avg_temp_min = sum(temp_min_values) / len(temp_min_values)
            avg_temp_max = sum(temp_max_values) / len(temp_max_values)
            
            avg_humid = sum(humid_values) / len(humid_values)
            avg_humid_min = sum(humid_min_values) / len(humid_min_values)
            avg_humid_max = sum(humid_max_values) / len(humid_max_values)
        else:
            avg_temp = avg_temp_min = avg_temp_max = None
            avg_humid = avg_humid_min = avg_humid_max = None
        
        return {
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days_with_data': days_with_data
            },
            'movement': {
                'daily_avg': round(avg_movement, 1),
                'hourly_avg': avg_hourly,
            },
            'temperature': {
                'avg': round(avg_temp, 1) if avg_temp is not None else None,
                'min': round(avg_temp_min, 1) if avg_temp_min is not None else None,
                'max': round(avg_temp_max, 1) if avg_temp_max is not None else None,
            },
            'humidity': {
                'avg': round(avg_humid, 1) if avg_humid is not None else None,
                'min': round(avg_humid_min, 1) if avg_humid_min is not None else None,
                'max': round(avg_humid_max, 1) if avg_humid_max is not None else None,
            }
        }
    
    def _calculate_activity_shift(self, current_hours, previous_hours):
        """
        Calculate how much the activity pattern has shifted.
        
        Args:
            current_hours (list): Hourly distribution for current day
            previous_hours (list): Hourly distribution for previous day
            
        Returns:
            float: Correlation coefficient (-1 to 1) where 1 is identical patterns,
                  0 is no correlation, and -1 is inverse patterns
        """
        # Normalize the distributions
        current_sum = sum(current_hours)
        previous_sum = sum(previous_hours)
        
        if current_sum == 0 or previous_sum == 0:
            return 0
        
        current_norm = [count / current_sum for count in current_hours]
        previous_norm = [count / previous_sum for count in previous_hours]
        
        # Calculate correlation
        try:
            correlation = np.corrcoef(current_norm, previous_norm)[0, 1]
            return round(correlation, 2)
        except:
            return 0
    
    def _save_report(self, report, target_date):
        """
        Save the daily report in various formats.
        
        Args:
            report (dict): Daily statistics report
            target_date (datetime.date): Date of the report
        """
        date_str = target_date.isoformat()
        report_dir = self.output_dir / date_str
        report_dir.mkdir(parents=True, exist_ok=True)
        
        # Save as JSON
        json_path = report_dir / 'daily_report.json'
        with open(json_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        # Save as CSV (flattened)
        csv_path = report_dir / 'daily_stats.csv'
        self._save_csv_report(report, csv_path)
        
        # Save summary text
        summary_path = report_dir / 'summary.txt'
        with open(summary_path, 'w') as f:
            f.write(self._generate_text_summary(report))
        
        logger.info(f"Report saved to {report_dir}")
        
        # Send notifications if enabled
        if self.config['telegram_notifications']:
            self._send_telegram_notification(report)
    
    def _save_csv_report(self, report, csv_path):
        """
        Save a flattened version of the report as CSV.
        
        Args:
            report (dict): Daily statistics report
            csv_path (Path): Path to save CSV file
        """
        # Flatten the report structure for CSV
        flat_data = {
            'date': report['date'],
            'movement_count': report['movement']['total_events'],
            'peak_activity_hour': report['movement']['peak_hour'],
            'active_hours': len(report['movement']['active_hours']),
            'temperature_avg': report['environment']['temperature']['avg'],
            'temperature_min': report['environment']['temperature']['min'],
            'temperature_max': report['environment']['temperature']['max'],
            'humidity_avg': report['environment']['humidity']['avg'],
            'humidity_min': report['environment']['humidity']['min'],
            'humidity_max': report['environment']['humidity']['max'],
            'vs_yesterday_movement_pct': report['comparisons']['previous_day']['movement']['percent_change'],
            'vs_yesterday_temp_diff': report['comparisons']['previous_day']['temperature']['avg_diff'],
            'vs_yesterday_humidity_diff': report['comparisons']['previous_day']['humidity']['avg_diff'],
            'vs_week_movement_pct': report['comparisons']['previous_week']['movement']['percent_change'],
            'vs_week_temp_diff': report['comparisons']['previous_week']['temperature']['avg_diff'],
            'vs_week_humidity_diff': report['comparisons']['previous_week']['humidity']['avg_diff'],
            'week_avg_movement': report['comparisons']['weekly_avg']['movement']['daily_avg'],
            'week_avg_temp': report['comparisons']['weekly_avg']['temperature']['avg'],
            'week_avg_humidity': report['comparisons']['weekly_avg']['humidity']['avg'],
        }
        
        # Check if file exists to determine if we need headers
        file_exists = Path(csv_path).exists()
        
        # Write to CSV
        with open(csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=flat_data.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(flat_data)
    
    def _generate_text_summary(self, report):
        """
        Generate a human-readable summary of the daily report.
        
        Args:
            report (dict): Daily statistics report
            
        Returns:
            str: Formatted text summary
        """
        date_str = report['date']
        mvmt = report['movement']
        env = report['environment']
        vs_day = report['comparisons']['previous_day']
        vs_week = report['comparisons']['weekly_avg']
        
        # Build summary
        lines = []
        lines.append(f"DAILY TURTLE ACTIVITY REPORT: {date_str}")
        lines.append("=" * 40)
        lines.append("")
        
        # Movement summary
        lines.append("MOVEMENT ACTIVITY:")
        lines.append(f"  Total movement events: {mvmt['total_events']}")
        
        if mvmt['total_events'] > 0:
            lines.append(f"  Peak activity hour: {mvmt['peak_hour']}:00")
            lines.append(f"  Active hours: {len(mvmt['active_hours'])}")
            lines.append(f"  Morning activity: {mvmt['morning_activity']}%")
            lines.append(f"  Afternoon activity: {mvmt['afternoon_activity']}%")
            lines.append(f"  Evening activity: {mvmt['evening_activity']}%")
            lines.append(f"  Night activity: {mvmt['night_activity']}%")
        else:
            lines.append("  No movement detected today.")
        
        lines.append("")
        
        # Environmental summary
        lines.append("ENVIRONMENTAL CONDITIONS:")
        if env['temperature']['count'] > 0:
            lines.append(f"  Average temperature: {env['temperature']['avg']}°C")
            lines.append(f"  Temperature range: {env['temperature']['min']} - {env['temperature']['max']}°C")
            lines.append(f"  Average humidity: {env['humidity']['avg']}%")
            lines.append(f"  Humidity range: {env['humidity']['min']} - {env['humidity']['max']}%")
        else:
            lines.append("  No environmental data recorded today.")
        
        lines.append("")
        
        # Comparison with yesterday
        lines.append("COMPARISON WITH YESTERDAY:")
        mvmt_change = vs_day['movement']['percent_change']
        mvmt_diff = vs_day['movement']['difference']
        if mvmt_diff > 0:
            lines.append(f"  Movement: {mvmt_diff} more events (+{mvmt_change}%)")
        elif mvmt_diff < 0:
            lines.append(f"  Movement: {abs(mvmt_diff)} fewer events ({mvmt_change}%)")
        else:
            lines.append("  Movement: Same as yesterday")
            
        if env['temperature']['count'] > 0:
            temp_diff = vs_day['temperature']['avg_diff']
            if temp_diff > 0:
                lines.append(f"  Temperature: {temp_diff}°C warmer")
            elif temp_diff < 0:
                lines.append(f"  Temperature: {abs(temp_diff)}°C cooler")
            else:
                lines.append("  Temperature: Same as yesterday")
                
            humid_diff = vs_day['humidity']['avg_diff']
            if humid_diff > 0:
                lines.append(f"  Humidity: {humid_diff}% higher")
            elif humid_diff < 0:
                lines.append(f"  Humidity: {abs(humid_diff)}% lower")
            else:
                lines.append("  Humidity: Same as yesterday")
                
            lines.append(f"  Activity pattern correlation: {vs_day['movement']['pattern_shift']}")
            if vs_day['movement']['pattern_shift'] > 0.7:
                lines.append("    (Very similar activity pattern to yesterday)")
            elif vs_day['movement']['pattern_shift'] < -0.3:
                lines.append("    (Opposite activity pattern from yesterday)")
        
        lines.append("")
        
        # Comparison with weekly average
        lines.append("COMPARISON WITH WEEKLY AVERAGE:")
        week_mvmt = vs_week['movement']['daily_avg']
        if mvmt['total_events'] > week_mvmt:
            lines.append(f"  Movement: {round(mvmt['total_events'] - week_mvmt, 1)} more events than weekly average")
        elif mvmt['total_events'] < week_mvmt:
            lines.append(f"  Movement: {round(week_mvmt - mvmt['total_events'], 1)} fewer events than weekly average")
        else:
            lines.append("  Movement: Same as weekly average")
            
        if env['temperature']['count'] > 0 and vs_week['temperature']['avg'] is not None:
            temp_diff = env['temperature']['avg'] - vs_week['temperature']['avg']
            if temp_diff > 0:
                lines.append(f"  Temperature: {round(temp_diff, 1)}°C warmer than weekly average")
            elif temp_diff < 0:
                lines.append(f"  Temperature: {round(abs(temp_diff), 1)}°C cooler than weekly average")
            else:
                lines.append("  Temperature: Same as weekly average")
                
            humid_diff = env['humidity']['avg'] - vs_week['humidity']['avg']
            if humid_diff > 0:
                lines.append(f"  Humidity: {round(humid_diff, 1)}% higher than weekly average")
            elif humid_diff < 0:
                lines.append(f"  Humidity: {round(abs(humid_diff), 1)}% lower than weekly average")
            else:
                lines.append("  Humidity: Same as weekly average")
        
        return "\n".join(lines)
    
    def _generate_charts(self, report, target_date):
        """
        Generate visualizations based on the daily report.
        
        Args:
            report (dict): Daily statistics report
            target_date (datetime.date): Date of the report
        """
        date_str = target_date.isoformat()
        chart_dir = self.output_dir / date_str / 'charts'
        chart_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate movement activity chart
        self._generate_movement_chart(report, chart_dir / 'movement.png')
        
        # Generate environmental charts
        self._generate_environment_chart(report, chart_dir / 'environment.png')
        
        # Generate comparison charts
        self._generate_comparison_chart(report, chart_dir / 'comparison.png')
        
        logger.info(f"Charts saved to {chart_dir}")
    
    def _generate_movement_chart(self, report, save_path):
        """
        Generate and save a chart showing hourly movement activity.
        
        Args:
            report (dict): Daily statistics report
            save_path (Path): Path to save the chart
        """
        hourly_data = report['movement']['hourly_distribution']
        weekly_avg = report['comparisons']['weekly_avg']['movement']['hourly_avg']
        
        # Create the figure and axis
        plt.figure(figsize=(10, 6))
        plt.bar(range(24), hourly_data, color='skyblue', alpha=0.7, label='Today')
        plt.plot(range(24), weekly_avg, marker='o', color='orange', label='Weekly Avg')
        
        # Add labels and formatting
        plt.title(f"Hourly Movement Activity - {report['date']}")
        plt.xlabel("Hour of Day (24h)")
        plt.ylabel("Movement Events")
        plt.xticks(range(0, 24, 2))
        plt.grid(axis='y', linestyle='--', alpha=0.7)
        plt.legend()
        
        # Add time zone indicators
        plt.axvspan(6, 18, alpha=0.1, color='yellow', label='Daylight')
        
        # Save and close
        plt.tight_layout()
        plt.savefig(save_path)
        plt.close()
    
    def _generate_environment_chart(self, report, save_path):
        """
        Generate and save a chart showing temperature and humidity trends.
        
        Args:
            report (dict): Daily statistics report
            save_path (Path): Path to save the chart
        """
        # Check if we have data
        if report['environment']['temperature']['count'] == 0:
            return
            
        temp_data = report['environment']['temperature']['hourly']
        humid_data = report['environment']['humidity']['hourly']
        hours = range(24)
        
        # Create figure with two y-axes
        fig, ax1 = plt.subplots(figsize=(10, 6))
        
        # Plot temperature
        ax1.set_xlabel('Hour of Day (24h)')
        ax1.set_ylabel('Temperature (°C)', color='tab:red')
        ax1.plot(hours, temp_data, color='tab:red', marker='o')
        ax1.tick_params(axis='y', labelcolor='tab:red')
        ax1.set_ylim(min(filter(None, temp_data)) - 2, max(filter(None, temp_data)) + 2)
        
        # Create second y-axis for humidity
        ax2 = ax1.twinx()
        ax2.set_ylabel('Humidity (%)', color='tab:blue')
        ax2.plot(hours, humid_data, color='tab:blue', marker='s')
        ax2.tick_params(axis='y', labelcolor='tab:blue')
        ax2.set_ylim(min(filter(None, humid_data)) - 5, max(filter(None, humid_data)) + 5)
        
        # Add title and grid
        plt.title(f"Temperature and Humidity - {report['date']}")
        ax1.grid(True, alpha=0.3)
        plt.xticks(range(0, 24, 2))
        
        # Add annotation for averages
        avg_temp = report['environment']['temperature']['avg']
        avg_humid = report['environment']['humidity']['avg']
        plt.figtext(0.15, 0.01, f"Avg Temp: {avg_temp}°C", fontsize=9)
        plt.figtext(0.35, 0.01, f"Avg Humidity: {avg_humid}%", fontsize=9)
        
        # Save and close
        fig.tight_layout()
        plt.savefig(save_path)
        plt.close()
    
    def _generate_comparison_chart(self, report, save_path):
        """
        Generate and save a chart comparing today with previous days and weekly average.
        
        Args:
            report (dict): Daily statistics report
            save_path (Path): Path to save the chart
        """
        # Extract data for comparison
        days = ['Today', 'Yesterday', 'Week Avg']
        
        movement_data = [
            report['movement']['total_events'],
            report['movement']['total_events'] - report['comparisons']['previous_day']['movement']['difference'],
            report['comparisons']['weekly_avg']['movement']['daily_avg']
        ]
        
        if report['environment']['temperature']['count'] > 0:
            temp_data = [
                report['environment']['temperature']['avg'],
                report['environment']['temperature']['avg'] - report['comparisons']['previous_day']['temperature']['avg_diff'],
                report['comparisons']['weekly_avg']['temperature']['avg']
            ]
            
            humid_data = [
                report['environment']['humidity']['avg'],
                report['environment']['humidity']['avg'] - report['comparisons']['previous_day']['humidity']['avg_diff'],
                report['comparisons']['weekly_avg']['humidity']['avg']
            ]
        else:
            temp_data = [0, 0, 0]
            humid_data = [0, 0, 0]
        
        # Create figure with subplots
        fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15, 5))
        
        # Movement comparison
        ax1.bar(days, movement_data, color=['skyblue', 'lightgray', 'orange'])
        ax1.set_title('Movement Events')
        ax1.set_ylabel('Count')
        
        # Temperature comparison
        ax2.bar(days, temp_data, color=['tomato', 'lightgray', 'orange'])
        ax2.set_title('Average Temperature')
        ax2.set_ylabel('°C')
        
        # Humidity comparison
        ax3.bar(days, humid_data, color=['cornflowerblue', 'lightgray', 'orange'])
        ax3.set_title('Average Humidity')
        ax3.set_ylabel('%')
        
        # Add overall title
        plt.suptitle(f"Daily Comparison - {report['date']}")
        
        # Save and close
        plt.tight_layout(rect=[0, 0, 1, 0.95])
        plt.savefig(save_path)
        plt.close()
    
    def _send_telegram_notification(self, report):
        """
        Send a summary of the daily report via Telegram.
        
        Args:
            report (dict): Daily statistics report
        """
        try:
            # Load config for Telegram integration
            config = load_yaml_config('config.yaml')
            if not config or 'telegram' not in config:
                logger.error("Telegram configuration not found")
                return
            
            token = config['telegram']['bot_token']
            chat_id = config['telegram']['chat_id']
            
            if not token or not chat_id:
                logger.error("Telegram bot_token or chat_id not configured")
                return
            
            # Create bot and send summary message
            bot = telegram.Bot(token=token)
            date_str = report['date']
            movement = report['movement']['total_events']
            
            # Construct a briefer version of the summary for Telegram
            message = f"📊 *Daily TurtleCam Report: {date_str}*\n\n"
            
            # Movement summary
            if movement > 0:
                message += f"🐢 *Movement:* {movement} events detected\n"
                message += f"⏰ Peak activity: {report['movement']['peak_hour']}:00 hours\n"
            else:
                message += "🐢 *Movement:* No activity detected today\n"
                
            # Environment summary
            if report['environment']['temperature']['count'] > 0:
                message += f"\n🌡️ *Temperature:* {report['environment']['temperature']['avg']}°C "
                message += f"(range: {report['environment']['temperature']['min']}-{report['environment']['temperature']['max']}°C)\n"
                message += f"💧 *Humidity:* {report['environment']['humidity']['avg']}% "
                message += f"(range: {report['environment']['humidity']['min']}-{report['environment']['humidity']['max']}%)\n"
            
            # Comparison
            message += "\n📈 *Compared to yesterday:*\n"
            
            # Movement comparison
            change = report['comparisons']['previous_day']['movement']['percent_change']
            if change > 0:
                message += f"🐢 {change}% more active\n"
            elif change < 0:
                message += f"🐢 {abs(change)}% less active\n"
            else:
                message += "🐢 Same activity level\n"
                
            # Send the message
            bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            
            # Check if we should also send charts
            if self.config['include_charts']:
                date_str = report['date']
                chart_dir = self.output_dir / date_str / 'charts'
                
                # Send movement chart
                movement_chart = chart_dir / 'movement.png'
                if movement_chart.exists():
                    with open(movement_chart, 'rb') as f:
                        bot.send_photo(chat_id=chat_id, photo=f, caption="Daily movement activity")
                
                # Send environment chart if data exists
                if report['environment']['temperature']['count'] > 0:
                    env_chart = chart_dir / 'environment.png'
                    if env_chart.exists():
                        with open(env_chart, 'rb') as f:
                            bot.send_photo(chat_id=chat_id, photo=f, caption="Temperature and humidity trends")
            
            logger.info("Daily report sent via Telegram")
            
        except Exception as e:
            logger.error(f"Failed to send Telegram notification: {e}")
