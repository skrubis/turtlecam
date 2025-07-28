#!/bin/bash
# TurtleCam Update Script
# Run this after pulling updates to deploy them to the running system

set -e

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

INSTALL_DIR="/opt/turtlecam"
REPO_DIR="$(pwd)"

echo -e "${GREEN}🔄 TurtleCam Update Script${NC}"
echo "=================================="

# Check if we're in the right directory
if [ ! -f "config.py" ] || [ ! -f "motion_detector.py" ]; then
    echo "❌ Please run this script from the turtlecam repository directory"
    exit 1
fi

# Check if install directory exists
if [ ! -d "$INSTALL_DIR" ]; then
    echo "❌ Installation directory $INSTALL_DIR not found"
    echo "Please run install.sh first"
    exit 1
fi

echo -e "${GREEN}📋 Copying updated files...${NC}"
sudo cp *.py "$INSTALL_DIR/"
sudo cp requirements.txt "$INSTALL_DIR/"
sudo chown turtle:turtle "$INSTALL_DIR"/*.py "$INSTALL_DIR/requirements.txt"

echo -e "${GREEN}📦 Updating Python dependencies...${NC}"
cd "$INSTALL_DIR"
source venv/bin/activate
pip install -r requirements.txt

echo -e "${GREEN}🔄 Restarting services...${NC}"
sudo systemctl restart turtle_motion.service turtle_bot.service

echo -e "${GREEN}📊 Checking service status...${NC}"
sudo systemctl status turtle_motion.service turtle_bot.service --no-pager -l

echo -e "${GREEN}✅ Update completed!${NC}"
echo
echo "Check logs with:"
echo "  journalctl -u turtle_motion.service -f"
echo "  journalctl -u turtle_bot.service -f"
