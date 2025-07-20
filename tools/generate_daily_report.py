#!/usr/bin/env python3
"""
Daily report generator script for TurtleCam.

This script is intended to be run daily (e.g., via cron) to generate the previous day's
activity report and optionally send notifications via Telegram.

Usage:
    python generate_daily_report.py [--no-charts] [--no-telegram] [--verbose]
"""
import sys
import os

# Add project root to PATH so we can import turtlecam modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

# Now we can import from turtlecam
from turtlecam.stats.cli import main

if __name__ == "__main__":
    main()
