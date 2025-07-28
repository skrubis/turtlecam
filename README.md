# TurtleCam 🐢

A smart terrarium monitoring system for Hermann's tortoises using Raspberry Pi 4 and Arducam Hawkeye 64MP camera. Automatically detects turtle movement, creates motion GIFs/videos, and sends alerts via Telegram.

## Features

- 🎥 **Motion Detection** - Background subtraction optimized for turtle behavior
- 📱 **Telegram Integration** - Real-time alerts and remote commands
- 🎬 **Automated GIF/Video Creation** - High-quality motion summaries
- 📊 **Data Collection** - Frame storage for future ML training (optional)
- ⚙️ **Systemd Services** - Reliable, auto-restarting system services
- 🗜️ **Smart Archiving** - Automatic data compression and cleanup

## Hardware Requirements

- **Raspberry Pi 4** (4GB RAM or higher recommended)
- **Arducam Hawkeye 64MP CSI-2 camera**
- **MicroSD card** (32GB or larger)
- **Optional**: Heatsink/fan for thermal management

## Quick Start

### 1. Prepare Raspberry Pi

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# If turtle user doesn't exist, create it:
# sudo useradd -m -s /bin/bash turtle

# Ensure turtle user has required permissions
sudo usermod -aG video,gpio turtle
```

### 2. Setup Arducam Hawkeye Camera

Follow the [official Arducam guide](https://docs.arducam.com/Raspberry-Pi-Camera/Native-camera/64MP-Hawkeye/) to:
- Enable camera interface (`sudo raspi-config`)
- Install camera drivers
- Test with `rpicam-hello --timeout 5000` (or `libcamera-hello` on older OS)

### 3. Install TurtleCam

```bash
# Switch to turtle user
sudo su - turtle

# Clone and install
git clone <your-repo-url> turtlecam
cd turtlecam
./install.sh
```

### 4. Configure Telegram

1. **Create Bot**: Message @BotFather → `/newbot` → save token
2. **Get Chat ID**: Message your bot, then visit:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
3. **Configure**: Edit `/opt/turtlecam/.env`:
   ```bash
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here  # Can be negative for groups
   ```

### 5. Start Services

```bash
sudo systemctl start turtle_motion.service turtle_bot.service turtle_pack.timer
sudo systemctl status turtle_motion.service turtle_bot.service
```

## Configuration

All settings are configured via `/opt/turtlecam/.env`:

### Required
```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### Optional (with defaults)
```bash
# Motion Detection
MOTION_THRESHOLD=25              # Sensitivity (lower = more sensitive)
INACTIVITY_TIMEOUT=8.0          # Seconds to end motion event

# Alert Settings
ALERT_FORMAT=gif                 # "gif" or "mp4"
ALERT_FPS=8.0                   # Playback frame rate

# ML Training Data (disabled by default)
SAVE_ML_FRAMES=false
ML_FRAMES_PATH=/mnt/external/turtle_ml_data

# System
LOG_LEVEL=INFO
```

## Telegram Commands

- `/photo` - Capture full-resolution still image
- `/gif [N]` - Create GIF from last N frames (default: 10)
- `/stats` - Show detection statistics
- `/status` - Show system status and resource usage
- `/help` - List all commands

## System Architecture

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
# Test camera (newer OS)
rpicam-hello --timeout 5000

# Or on older OS:
# libcamera-hello --timeout 5000

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

# Run system validation
python3 test_system.py
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

# Add to /etc/fstab for permanent mounting
echo '/dev/sda1 /mnt/external ext4 defaults 0 2' | sudo tee -a /etc/fstab
```

## Troubleshooting Common Issues

### "ModuleNotFoundError: No module named 'libcamera'"
This is a common issue when picamera2 can't find the libcamera Python bindings:

```bash
# Stop services
sudo systemctl stop turtle_motion.service turtle_bot.service

# Install system libcamera packages
sudo apt update
sudo apt install -y python3-libcamera python3-kms++

# Recreate venv with system packages access
cd /opt/turtlecam
sudo rm -rf venv
sudo python3 -m venv venv --system-site-packages
sudo chown -R turtle:turtle venv

# Reinstall requirements
source venv/bin/activate
pip install -r requirements.txt

# Restart services
sudo systemctl start turtle_motion.service turtle_bot.service
```

### "database or disk is full"
SQLite can't create the database when disk space is full:

```bash
# Check disk usage
df -h

# Free up space
sudo apt clean
sudo apt autoremove
sudo journalctl --vacuum-time=7d

# Check large files
sudo du -sh /* 2>/dev/null | sort -hr | head -10

# If /var/lib/turtle is on a small partition, move it:
sudo systemctl stop turtle_motion.service turtle_bot.service
sudo mv /var/lib/turtle /home/turtle/turtle_data
sudo ln -s /home/turtle/turtle_data /var/lib/turtle
sudo systemctl start turtle_motion.service turtle_bot.service
```

### "No camera detected"
- Check CSI cable connection
- Enable camera: `sudo raspi-config` → Interface Options → Camera
- Test: `rpicam-hello --timeout 5000` (or `libcamera-hello` on older OS)
- Reboot after enabling

### "Motion detection not working"
- Check camera preview: `rpicam-hello` (or `libcamera-hello` on older OS)
- Adjust `MOTION_THRESHOLD` in `.env`
- Check logs: `journalctl -u turtle_motion.service`

### "Telegram bot not responding"
- Verify bot token and chat ID
- Test connectivity: `curl https://api.telegram.org/bot<TOKEN>/getMe`
- Check logs: `journalctl -u turtle_bot.service`

### "Disk space full"
- Run cleanup: `python3 archive_manager.py --cleanup`
- Check settings: `ML_FRAMES_PATH` pointing to external drive
- Reduce `MAX_AGE_DAYS` in config

### "High CPU usage"
- Lower preview FPS in config
- Increase `MOTION_THRESHOLD`
- Check for memory leaks in logs

### "False motion alerts"
- Increase `MOTION_THRESHOLD`
- Adjust `MIN_BLOB_AREA`
- Check for reflections or lighting changes

## Service Management

### Systemd Services

The system runs three main services:

- **`turtle_motion.service`** - Motion detection and frame capture
- **`turtle_bot.service`** - Telegram bot for commands and alerts
- **`turtle_pack.timer`** - Daily archiving (runs at 2:00 AM)

### Service Commands
```bash
# Start services
sudo systemctl start turtle_motion.service turtle_bot.service

# Stop services
sudo systemctl stop turtle_motion.service turtle_bot.service

# Enable auto-start on boot
sudo systemctl enable turtle_motion.service turtle_bot.service turtle_pack.timer

# Check service status
sudo systemctl status turtle_motion.service

# View service logs
journalctl -u turtle_motion.service --since "1 hour ago"

# Restart failed services
sudo systemctl restart turtle_motion.service
```

## Data Management

### Archive System

TurtleCam automatically manages data storage:

- **Daily frames** stored in `/var/lib/turtle/frames/YYYY-MM-DD/`
- **Automatic archiving** compresses old data into `.tar.zst` files
- **Cleanup** removes data older than 30 days (configurable)
- **ML frames** optionally saved to external drive

### Manual Archive Operations
```bash
cd /opt/turtlecam && source venv/bin/activate

# Archive specific date
python3 archive_manager.py --archive-date 2024-01-15

# Show archive statistics
python3 archive_manager.py --stats

# Extract archive for inspection
python3 archive_manager.py --extract 2024-01-15.tar.zst

# Force cleanup with custom age
python3 archive_manager.py --cleanup --max-age 7
```

## Security Considerations

### Systemd Hardening

Services run with security hardening:
- Non-root user (`turtle`)
- Restricted file system access
- No new privileges
- Private temporary directories
- Resource accounting enabled

### Network Security

- Bot token stored in protected `.env` file (600 permissions)
- No external network services exposed
- Telegram communication over HTTPS only

### File Permissions
```bash
# Secure configuration file
sudo chmod 600 /opt/turtlecam/.env
sudo chown turtle:turtle /opt/turtlecam/.env

# Secure data directory
sudo chmod 755 /var/lib/turtle
sudo chown -R turtle:turtle /var/lib/turtle
```

## Contributing

1. Fork the repository
2. Create feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push branch: `git push origin feature/amazing-feature`
5. Open Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add tests for new features
- Update documentation
- Test on actual Raspberry Pi hardware when possible

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- **Arducam** for the excellent 64MP camera module
- **Raspberry Pi Foundation** for the platform
- **python-telegram-bot** library maintainers
- **OpenCV** community

## Support

For support, please:
1. Check the troubleshooting section
2. Search existing GitHub issues
3. Create a new issue with detailed information

Include the following in bug reports:
- Raspberry Pi model and OS version
- Camera model and connection
- Relevant log excerpts
- Configuration settings (without sensitive tokens)

---

**Happy turtle watching! 🐢📸**

*Optimized for Hermann's tortoises but adaptable for other species.*
