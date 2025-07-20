#!/usr/bin/env python3
"""
Command-line interface for generating daily turtle activity reports.
"""
import argparse
import datetime
import logging
import sys
from pathlib import Path

from turtlecam.stats.daily_stats import DailyStatsReporter
from turtlecam.system.config import load_yaml_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("stats_cli")

def parse_date(date_str):
    """Parse a date string in YYYY-MM-DD format."""
    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        logger.error(f"Invalid date format: {date_str}. Use YYYY-MM-DD.")
        return None

def main():
    """Main entry point for the daily stats CLI."""
    parser = argparse.ArgumentParser(
        description="Generate daily turtle activity reports"
    )
    
    parser.add_argument(
        "--date", "-d",
        help="Target date for report in YYYY-MM-DD format (defaults to yesterday)",
        default=None
    )
    
    parser.add_argument(
        "--config", "-c",
        help="Path to config file",
        default="config.yaml"
    )
    
    parser.add_argument(
        "--output", "-o",
        help="Output directory for reports",
        default=None
    )
    
    parser.add_argument(
        "--no-charts", 
        help="Disable chart generation",
        action="store_true",
        default=False
    )
    
    parser.add_argument(
        "--no-telegram", 
        help="Disable Telegram notifications",
        action="store_true",
        default=False
    )
    
    parser.add_argument(
        "--verbose", "-v",
        help="Enable verbose output",
        action="store_true",
        default=False
    )
    
    args = parser.parse_args()
    
    # Configure logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        
    # Load config
    config = load_yaml_config(args.config)
    if not config:
        logger.error(f"Failed to load config from {args.config}")
        sys.exit(1)
    
    # Parse target date
    if args.date:
        target_date = parse_date(args.date)
        if not target_date:
            sys.exit(1)
    else:
        # Default to yesterday
        target_date = datetime.date.today() - datetime.timedelta(days=1)
    
    logger.info(f"Generating report for {target_date.isoformat()}")
    
    # Configure reporter options
    reporter_config = {
        "telegram_notifications": not args.no_telegram,
        "include_charts": not args.no_charts,
    }
    
    # Set output directory if specified
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        reporter_config["output_dir"] = output_dir
    
    # Generate the report
    try:
        reporter = DailyStatsReporter(config, reporter_config)
        report = reporter.generate_report(target_date)
        
        # Print summary info
        print(f"\nReport for {target_date.isoformat()} generated successfully")
        print(f"Movement events: {report['movement']['total_events']}")
        if report['environment']['temperature']['count'] > 0:
            print(f"Average temperature: {report['environment']['temperature']['avg']}°C")
            print(f"Average humidity: {report['environment']['humidity']['avg']}%")
        
        # Print output location
        output_dir = reporter_config.get("output_dir", reporter.output_dir)
        print(f"\nFull report saved to: {output_dir / target_date.isoformat()}")
        
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
