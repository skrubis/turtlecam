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
| `/temp` | Get current temperature and humidity readings |
| `/light on` | Turn light on (manual override) |
| `/light off` | Turn light off (manual override) |
| `/heat on` | Turn heating on (manual override) |
| `/heat off` | Turn heating off (manual override) |
| `/fan on` | Turn fan on (manual override) |
| `/fan off` | Turn fan off (manual override) |
| `/filter on` | Turn filter on (manual override) |
| `/filter off` | Turn filter off (manual override) |
| `/reset` | Clear all manual overrides and return to schedule |
| `/help` | Show available commands |

## Testing

### Running Unit Tests

TurtleCam includes a comprehensive test suite to ensure each module functions correctly:

```bash
# Run all tests
python -m unittest discover -s tests

# Run a specific test module
python -m unittest tests.test_env_monitor

# Run a specific test case
python -m unittest tests.test_relay.TestRelayController.test_safety_shutdown
```

### Mock Mode

For development and testing without actual hardware, use mock mode:

```yaml
# In config.yaml
system:
  mock_mode: true
```

In mock mode:
- DHT22 sensor readings are simulated with random values
- GPIO pins aren't actually toggled
- Camera operations use test images if available

### Test Coverage

To generate test coverage reports:

```bash
# Install coverage package
pip install coverage

# Run tests with coverage
coverage run -m unittest discover

# Generate coverage report
coverage report -m

# Generate HTML coverage report
coverage html
```

## Troubleshooting

### Common Issues

#### Camera Not Working

```bash
# Check if camera is detected
vcgencmd get_camera
# Should return: supported=1 detected=1

# Make sure the camera interface is enabled
sudo raspi-config
# Navigate to Interface Options -> Camera and enable it

# Check logs for camera errors
journalctl -u turtlecam -f
```

#### DHT22 Sensor Issues

```bash
# Check if the I2C interface is enabled
sudo raspi-config

# Check I2C device detection
i2cdetect -y 1

# Check wiring connections (common issue)
# DHT22 pin 1 -> 3.3V power
# DHT22 pin 2 -> GPIO data pin (with 10k pull-up resistor)
# DHT22 pin 3 -> not connected
# DHT22 pin 4 -> Ground
```

#### Relay Control Problems

- Verify GPIO pin numbers in config match your wiring
- Check relay module is powered properly (some need separate power)
- Ensure all ground connections are solid
- If using a relay module with active-low triggers, adjust the `relay_active_low` setting

#### System Time Issues

```bash
# Check NTP synchronization status
timedatectl status

# Check chronyd status
systemctl status chronyd

# If using DS3231, check if it's detected
i2cdetect -y 1
# Should show device at address 0x68
```

#### Log Files

Check logs for debugging:

```bash
# View system service logs
sudo journalctl -u turtlecam -f 

# Check application logs in the data directory
less data/turtlecam.log
```

## Soak Test Guide

Before deploying TurtleCam long-term, perform a soak test to ensure stability.

### Preparing for Soak Test

1. **Configure mock environmental events**:
   - Create a test script that simulates temperature fluctuations
   - Schedule test relay activations at different times

2. **Set up monitoring**:
   - Enable detailed logging: `log_level: DEBUG` in config
   - Configure log rotation to prevent filling storage
   - Set up a secondary monitoring solution (optional)

3. **Prepare storage for extended test**:
   - Ensure sufficient free space (at least 10GB recommended)
   - Configure aggressive storage management for testing:

```yaml
storage:
  retention_days: 2  # More aggressive for testing
  cleanup_threshold_pct: 70
  target_usage_pct: 60
  compress_older_than_days: 1
```

### Running the Soak Test

1. **Start the system**:
   ```bash
   sudo systemctl start turtlecam
   ```

2. **Duration**:
   - Minimum recommended test duration: 72 hours
   - Ideal test duration: 7-14 days

3. **Monitor key metrics**:
   - CPU usage: `top`, `htop` or `mpstat`
   - Memory usage: `free -m`
   - Disk usage: `df -h`
   - Temperature: `vcgencmd measure_temp`

4. **Verification checks**:
   - No memory leaks (stable RAM usage over time)
   - No unexpected restarts
   - All threads working correctly
   - Data being recorded properly
   - Telegram alerts functioning correctly
   - Storage management working as expected

### Analyzing Soak Test Results

After completing the soak test:

1. **Check logs for errors or warnings**:
   ```bash
   grep -E "ERROR|WARNING" data/turtlecam.log
   ```

2. **Verify database integrity**:
   ```bash
   sqlite3 data/turtlecam.db "PRAGMA integrity_check;"
   ```

3. **Review system statistics**:
   - Check relay activation counts and timing
   - Verify all scheduled events occurred
   - Analyze any temperature alert patterns

4. **Fine-tune settings**:
   - Adjust polling intervals if needed
   - Modify storage management parameters
   - Update alert thresholds based on observations

## Contributing

Contributions to TurtleCam are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests to ensure quality
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## License

MIT