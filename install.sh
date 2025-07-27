#!/bin/bash
# TurtleCam Installation Script
# Run this script as the turtle user on Raspberry Pi

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/turtlecam"
DATA_DIR="/var/lib/turtle"
LOG_DIR="/var/log/turtle"
USER="turtle"

echo -e "${GREEN}🐢 TurtleCam Installation Script${NC}"
echo "=================================="

# Check if running as turtle user
if [ "$USER" != "turtle" ]; then
    echo -e "${RED}❌ This script must be run as the 'turtle' user${NC}"
    echo "Switch to turtle user: sudo su - turtle"
    exit 1
fi

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo -e "${YELLOW}⚠️  Warning: This doesn't appear to be a Raspberry Pi${NC}"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo -e "${GREEN}📦 Installing system dependencies...${NC}"
sudo apt update
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    ffmpeg \
    sqlite3 \
    systemd \
    git

echo -e "${GREEN}📁 Creating directories...${NC}"
sudo mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$LOG_DIR"
sudo chown turtle:turtle "$DATA_DIR" "$LOG_DIR"
sudo chmod 755 "$DATA_DIR" "$LOG_DIR"

echo -e "${GREEN}🔧 Setting up Python virtual environment...${NC}"
sudo python3 -m venv "$INSTALL_DIR/venv"
sudo chown -R turtle:turtle "$INSTALL_DIR"

# Activate virtual environment
source "$INSTALL_DIR/venv/bin/activate"

echo -e "${GREEN}📚 Installing Python dependencies...${NC}"
pip install --upgrade pip
pip install -r requirements.txt

echo -e "${GREEN}📋 Copying application files...${NC}"
cp *.py "$INSTALL_DIR/"
cp requirements.txt "$INSTALL_DIR/"

# Create .env file if it doesn't exist
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo -e "${YELLOW}⚙️  Creating .env file from template...${NC}"
    cp .env.example "$INSTALL_DIR/.env"
    echo -e "${RED}❗ IMPORTANT: Edit $INSTALL_DIR/.env with your Telegram bot token and chat ID${NC}"
fi

echo -e "${GREEN}🔧 Creating systemd service files...${NC}"

# Motion detection service
sudo tee /etc/systemd/system/turtle_motion.service > /dev/null <<EOF
[Unit]
Description=TurtleCam Motion Detection
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=turtle
Group=turtle
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$INSTALL_DIR/venv/bin
ExecStart=$INSTALL_DIR/venv/bin/python3 motion_detector.py
Restart=on-failure
RestartSec=3
StandardOutput=journal
StandardError=journal

# Security hardening
ProtectSystem=strict
ReadWritePaths=$DATA_DIR $LOG_DIR /tmp
NoNewPrivileges=yes
PrivateTmp=yes

# Resource limits
CPUAccounting=yes
MemoryAccounting=yes
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
EOF

# Telegram bot service
sudo tee /etc/systemd/system/turtle_bot.service > /dev/null <<EOF
[Unit]
Description=TurtleCam Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=turtle
Group=turtle
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$INSTALL_DIR/venv/bin
ExecStart=$INSTALL_DIR/venv/bin/python3 telegram_bot.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

# Security hardening
ProtectSystem=strict
ReadWritePaths=$DATA_DIR $LOG_DIR /tmp
NoNewPrivileges=yes
PrivateTmp=yes

# Resource limits
CPUAccounting=yes
MemoryAccounting=yes
LimitNOFILE=4096

[Install]
WantedBy=multi-user.target
EOF

# GIF builder service (oneshot, triggered by motion or commands)
sudo tee /etc/systemd/system/turtle_gif.service > /dev/null <<EOF
[Unit]
Description=TurtleCam GIF Builder
After=turtle_motion.service

[Service]
Type=oneshot
User=turtle
Group=turtle
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$INSTALL_DIR/venv/bin
ExecStart=$INSTALL_DIR/venv/bin/python3 telegram_bot.py --alert
StandardOutput=journal
StandardError=journal

# Security hardening
ProtectSystem=strict
ReadWritePaths=$DATA_DIR $LOG_DIR /tmp
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF

# Daily archive service
sudo tee /etc/systemd/system/turtle_pack.service > /dev/null <<EOF
[Unit]
Description=TurtleCam Daily Archive
After=turtle_motion.service

[Service]
Type=oneshot
User=turtle
Group=turtle
WorkingDirectory=$INSTALL_DIR
Environment=PATH=$INSTALL_DIR/venv/bin
ExecStart=/bin/bash -c 'find $DATA_DIR/frames -name "*.jpg" -mtime +1 -exec rm {} \;'
StandardOutput=journal
StandardError=journal

# Security hardening
ProtectSystem=strict
ReadWritePaths=$DATA_DIR
NoNewPrivileges=yes
PrivateTmp=yes
EOF

# Daily archive timer
sudo tee /etc/systemd/system/turtle_pack.timer > /dev/null <<EOF
[Unit]
Description=TurtleCam Daily Archive Timer
Requires=turtle_pack.service

[Timer]
OnCalendar=daily
RandomizedDelaySec=300
Persistent=true

[Install]
WantedBy=timers.target
EOF

echo -e "${GREEN}🔄 Reloading systemd and enabling services...${NC}"
sudo systemctl daemon-reload
sudo systemctl enable turtle_motion.service
sudo systemctl enable turtle_bot.service
sudo systemctl enable turtle_pack.timer

echo -e "${GREEN}📝 Creating log rotation configuration...${NC}"
sudo tee /etc/logrotate.d/turtlecam > /dev/null <<EOF
$LOG_DIR/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 turtle turtle
    postrotate
        systemctl reload-or-restart turtle_motion.service turtle_bot.service
    endscript
}
EOF

echo -e "${GREEN}✅ Installation completed!${NC}"
echo
echo -e "${YELLOW}📋 Next steps:${NC}"
echo "1. Edit the configuration file:"
echo "   nano $INSTALL_DIR/.env"
echo
echo "2. Add your Telegram bot token and chat ID"
echo
echo "3. Test the configuration:"
echo "   cd $INSTALL_DIR && source venv/bin/activate && python3 -c 'from config import config; print(config.validate())'"
echo
echo "4. Start the services:"
echo "   sudo systemctl start turtle_motion.service"
echo "   sudo systemctl start turtle_bot.service"
echo "   sudo systemctl start turtle_pack.timer"
echo
echo "5. Check service status:"
echo "   sudo systemctl status turtle_motion.service"
echo "   sudo systemctl status turtle_bot.service"
echo
echo "6. View logs:"
echo "   journalctl -u turtle_motion.service -f"
echo "   journalctl -u turtle_bot.service -f"
echo
echo -e "${GREEN}🎉 Happy turtle watching!${NC}"
