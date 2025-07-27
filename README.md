# TurtleCam: Smart Turtle Terrarium Controller

A Raspberry Pi-based system that transforms a turtle terrarium into a "smart terrarium" with automated monitoring, environmental control, and alerts. TurtleCam captures moments when your turtle is active, monitors environmental conditions, and helps you maintain optimal habitat conditions through automated control systems.

## Features

- **Motion Detection**: Uses a 64MP Arducam to detect turtle activity and capture high-resolution images
- **Telegram Integration**: Automatically shares motion GIFs and allows remote control via a Telegram bot
- **Environmental Control**: Monitors temperature and humidity with DHT22 sensor
- **Automated Light & Heat**: Controls lighting and heating via relay board on a schedule
- **Data Collection**: Stores sensor data and images for future ML training
- **Time Synchronization**: Maintains accurate time with NTP and optional DS3231 RTC hardware clock
- **Storage Management**: Automatically compresses and archives old data to conserve space
- **ML Export**: Tools for exporting captured data in YOLO format for machine learning projects
- **Safety Features**: Automatic shutdown of heating elements during high temperature events
- **Daily Statistics Reports**: Generates daily reports with activity patterns, environmental data, and historical comparisons

## Hardware Requirements

- Raspberry Pi 4 (4GB RAM or higher)
- Arducam 64MP CSI-2 camera
- DHT22 temperature-humidity sensor
- 2-4 channel 5V relay board
- Optional: 5V fan for Pi cooling
- Optional: DS3231 RTC hardware clock

## System Architecture

TurtleCam consists of the following key modules:

1. **Vision Pipeline**: Motion detection, camera control, GIF creation, and crop storage
2. **Telegram Bot**: Alert notifications, remote commands, and configuration management
3. **Environmental Monitor**: DHT22 sensor polling, temperature/humidity logging, and alert monitoring
4. **Relay Controller**: Scheduled and manual control of lights, heating, filtration, and fans
5. **Data Store**: SQLite database and directory structure for data persistence
6. **Time Sync**: Time synchronization with NTP and optional RTC hardware
7. **Storage Manager**: Automatic data archiving, compression, and disk space management
8. **Stats Reporter**: Daily statistics reporting with activity patterns and environmental data analysis

## Installation

### Prerequisites

```bash
# Enable camera and I2C interface on Raspberry Pi
sudo raspi-config
# Navigate to Interface Options and enable Camera and I2C

# Install required system packages
sudo apt update
sudo apt install -y python3-pip python3-venv libopenjp2-7 libatlas-base-dev
sudo apt install -y i2c-tools libilmbase-dev libopenexr-dev libgstreamer1.0-dev
sudo apt install -y chrony # For time synchronization
```

### Installation Steps

```bash
# Clone the repository
git clone https://github.com/skrubis/turtlecam.git
cd turtlecam

# Create a virtual environment
python3 -m venv venv

# Activate the virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
.\venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure your environment by copying the example files.
# On Linux/macOS:
cp .env.example .env
cp config.example.yaml config.yaml

# On Windows:
copy .env.example .env
copy config.example.yaml config.yaml

# Edit .env with your Telegram bot token and chat ID.
# Edit config.yaml to customize your setup (e.g., camera, sensors).
```

## Configuration

TurtleCam uses YAML configuration files with sensible defaults. Edit `config.yaml` to customize your setup:

### Core Configuration

```yaml
# Main configuration parameters
system:
  mock_mode: false  # Set to true for development without hardware
  log_level: INFO   # DEBUG, INFO, WARNING, ERROR
  base_path: data   # Base directory for data storage

# Camera settings
camera:
  resolution: [2048, 1536]  # Camera resolution
  framerate: 15             # Framerate in fps
  rotation: 0               # Camera rotation (0, 90, 180, 270)
```

### Environmental Settings

```yaml
# Environmental monitor settings
environment:
  sensor_pin: 4             # GPIO pin for DHT22 sensor
  poll_interval: 60         # Seconds between readings
  min_temp: 20              # Minimum safe temperature (°C)
  max_temp: 32              # Maximum safe temperature (°C)
  alert_cooldown: 3600      # Seconds between repeat alerts
```

### Relay Control

```yaml
# Relay control configuration
relay:
  pins:                      # GPIO pins for relays
    light: 17
    heat: 27
    filter: 22
    fan: 23
  schedule:                  # Daily schedule
    light:
      - {on: "08:00", off: "20:00"}
    heat:
      - {on: "06:00", off: "22:00", condition: "temp_below:26"}
    filter:
      - {on: "00:00", off: "23:59"}
    fan:
      - {on: "12:00", off: "14:00"}
      - {on: "18:00", off: "20:00"}
```

## Usage

### Running as a Service (Linux/Raspberry Pi Only)

To install TurtleCam as a systemd service for automatic startup on a Linux system, use the following commands. This is the recommended way to run the application on a Raspberry Pi.

```bash
# Copy the service file (note the correct path)
sudo cp systemd/turtlecam.service /etc/systemd/system/

# Reload the systemd daemon, enable and start the service
sudo systemctl daemon-reload
sudo systemctl enable turtlecam.service
sudo systemctl start turtlecam.service

# Check the status of the service
sudo systemctl status turtlecam.service
```

### Manual Running

To run the application manually from the command line for development or testing:

```bash
# Activate the virtual environment
# On Linux/macOS:
source venv/bin/activate
# On Windows:
.\venv\Scripts\activate

# Start the main application
python -m turtlecam.main

# Or with a custom config path
python -m turtlecam.main --config /path/to/custom/config.yaml
```

### Generating Daily Reports

Daily statistics reports are generated automatically each day (at the time specified in config.yaml). You can also generate reports manually:

```bash
# Generate a report for yesterday (default)
python tools/generate_daily_report.py

# Generate a report for a specific date
python tools/generate_daily_report.py --date 2023-09-15

# Generate a report without sending Telegram notifications
python tools/generate_daily_report.py --no-telegram

# Generate a report without charts
python tools/generate_daily_report.py --no-charts

# Specify a custom output directory
python tools/generate_daily_report.py --output /path/to/reports
```

Reports include:
- Movement activity statistics (total events, hourly distribution, peak activity hours)
- Environmental data analysis (temperature and humidity averages, ranges, patterns)
- Comparative analysis with previous day and weekly averages
- Visual charts for activity patterns and environmental trends

## Telegram Bot Commands

Once running, interact with TurtleCam through these Telegram commands:

| Command | Description |
|---------|-------------|
| `/status` | Get current system status including temperature/humidity readings |
| `/photo` | Take and send a photo from the camera |
| `/relays` | Show current state of all relays |
```
Arducam 64MP Camera
       ↓
VGA Preview (Motion Detection) → High-res Crops → GIF/Video Builder
       ↓                              ↓                    ↓
SQLite Database ←─────────────────────┘                    ↓
                                                           ↓
Telegram Bot ←─────────────────────────────────────────────┘
```

### Components

- **`motion_detector.py`** - Background subtraction motion detection
- **`gif_builder.py`** - Creates GIFs/videos from motion frames
- **`telegram_bot.py`** - Handles Telegram commands and alerts
- **`database.py`** - SQLite storage for detection metadata
- **`archive_manager.py`** - Daily data compression and cleanup
- **`config.py`** - Centralized configuration management

## File Structure

```
/opt/turtlecam/              # Application
├── venv/                    # Python environment
├── *.py                     # Application modules
└── .env                     # Configuration

/var/lib/turtle/             # Data storage
├── frames/YYYY-MM-DD/       # Daily motion frames
├── archives/                # Compressed archives
└── detections.db           # SQLite database

/var/log/turtle/             # Logs
├── motion.log
└── bot.log
```

## Monitoring & Troubleshooting

### Check Services
```bash
# Service status
sudo systemctl status turtle_motion.service turtle_bot.service

# Live logs
journalctl -u turtle_motion.service -f
journalctl -u turtle_bot.service -f

# Restart services
sudo systemctl restart turtle_motion.service turtle_bot.service
```

### Test Camera
```bash
# Test camera
libcamera-hello --timeout 5000

# Check detection
vcgencmd get_camera
```

### Storage Management
```bash
# Check disk usage
df -h /var/lib/turtle

# Manual cleanup
cd /opt/turtlecam && source venv/bin/activate
python3 archive_manager.py --cleanup --max-age 14

# Archive statistics
python3 archive_manager.py --stats
```

### Test Telegram
```bash
# Test bot connectivity
curl -s "https://api.telegram.org/bot<YOUR_TOKEN>/getMe"

# Manual alert test
cd /opt/turtlecam && source venv/bin/activate
python3 telegram_bot.py --alert
```

## Performance Tuning

### Optimize for Performance
```bash
# Increase GPU memory
echo 'gpu_mem=128' | sudo tee -a /boot/config.txt

# Performance CPU governor
echo 'performance' | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor
```

### Optimize for Low Resources
```bash
# In .env file:
MOTION_THRESHOLD=50          # Less sensitive
ALERT_FPS=4.0               # Lower frame rate
MAX_ALERT_FRAMES=8          # Fewer frames
```

## Development

### Setup Development Environment
```bash
cd /opt/turtlecam
source venv/bin/activate

# Install development dependencies
pip install pytest ruff

# Run tests
pytest tests/

# Code formatting
ruff format .
ruff check .
```

### Manual Testing
```bash
# Test motion detection
python3 motion_detector.py

# Test GIF creation
python3 gif_builder.py --frames 10

# Test Telegram bot
python3 telegram_bot.py
```

## Customization

### Adjust for Different Turtle Species

Edit motion detection parameters in `.env`:

```bash
# For faster turtles (e.g., box turtles)
INACTIVITY_TIMEOUT=4.0
MOTION_THRESHOLD=20

# For slower turtles (e.g., large tortoises)
INACTIVITY_TIMEOUT=12.0
MOTION_THRESHOLD=30
```

### Enable ML Data Collection

```bash
# In .env file:
SAVE_ML_FRAMES=true
ML_FRAMES_PATH=/mnt/external/turtle_training_data

# Mount external drive
sudo mkdir -p /mnt/external
sudo mount /dev/sda1 /mnt/external