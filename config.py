"""
TurtleCam Configuration Management
Handles all configurable parameters with sensible defaults for Hermann's tortoise monitoring.
"""

import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv


@dataclass
class CameraConfig:
    """Camera and preview settings"""
    preview_width: int = 640
    preview_height: int = 480
    preview_fps: int = 15
    full_res_width: int = 9152  # Arducam Hawkeye 64MP
    full_res_height: int = 6944
    crop_margin_percent: float = 15.0  # Margin around detected object


@dataclass
class MotionConfig:
    """Motion detection parameters"""
    motion_threshold: int = 25  # Background subtraction threshold
    min_blob_area: int = 1000  # Minimum area in pixels for motion detection
    morphology_kernel_size: int = 5  # For noise reduction
    inactivity_timeout: float = 8.0  # Seconds of no motion to end event (Hermann's tortoises move slowly)
    background_learning_rate: float = 0.01  # How quickly background adapts


@dataclass
class AlertConfig:
    """GIF/Video alert settings"""
    output_format: str = "gif"  # "gif" or "mp4"
    max_frames: int = 16  # Maximum frames in output
    target_fps: float = 8.0  # Playback FPS (good balance for smooth motion)
    max_duration: float = 4.0  # Maximum duration in seconds
    max_width: int = 1920  # Downscale width for alerts
    quality: int = 85  # JPEG quality for frames


@dataclass
class TelegramConfig:
    """Telegram bot settings"""
    bot_token: str = ""
    chat_id: str = ""  # Can be negative for groups
    rate_limit_delay: float = 2.0  # Minimum seconds between messages
    max_retries: int = 3
    retry_backoff: float = 2.0  # Exponential backoff multiplier


@dataclass
class StorageConfig:
    """Data storage settings"""
    base_path: str = "/var/lib/turtle"
    frames_subdir: str = "frames"
    archives_subdir: str = "archives"
    database_file: str = "detections.db"
    
    # ML training data collection (disabled by default)
    save_ml_frames: bool = False
    ml_frames_path: Optional[str] = None  # Can be external drive path
    
    # Cleanup settings
    max_age_days: int = 30
    max_disk_usage_percent: float = 80.0


@dataclass
class SystemConfig:
    """System and performance settings"""
    log_level: str = "INFO"
    max_cpu_percent: float = 60.0
    max_memory_mb: int = 2048
    watchdog_timeout: int = 30  # Systemd watchdog timeout


class Config:
    """Main configuration class that loads from environment and config files"""
    
    def __init__(self, config_file: Optional[str] = None):
        self.camera = CameraConfig()
        self.motion = MotionConfig()
        self.alert = AlertConfig()
        self.telegram = TelegramConfig()
        self.storage = StorageConfig()
        self.system = SystemConfig()
        
        # Load .env file first (use absolute path)
        env_file = Path(__file__).parent / '.env'
        load_dotenv(env_file)
        
        # Load from .env file
        self._load_env()
        
        # Override with config file if provided
        if config_file and os.path.exists(config_file):
            self._load_config_file(config_file)
    
    def _load_env(self):
        """Load configuration from environment variables"""
        # Telegram settings (required)
        self.telegram.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        
        # Optional overrides
        if os.getenv("MOTION_THRESHOLD"):
            self.motion.motion_threshold = int(os.getenv("MOTION_THRESHOLD"))
        
        if os.getenv("INACTIVITY_TIMEOUT"):
            self.motion.inactivity_timeout = float(os.getenv("INACTIVITY_TIMEOUT"))
        
        if os.getenv("ALERT_FORMAT"):
            self.alert.output_format = os.getenv("ALERT_FORMAT")
        
        if os.getenv("ALERT_FPS"):
            self.alert.target_fps = float(os.getenv("ALERT_FPS"))
        
        if os.getenv("SAVE_ML_FRAMES"):
            self.storage.save_ml_frames = os.getenv("SAVE_ML_FRAMES").lower() == "true"
        
        if os.getenv("ML_FRAMES_PATH"):
            self.storage.ml_frames_path = os.getenv("ML_FRAMES_PATH")
        
        if os.getenv("LOG_LEVEL"):
            self.system.log_level = os.getenv("LOG_LEVEL")
    
    def _load_config_file(self, config_file: str):
        """Load configuration from YAML/JSON file (future enhancement)"""
        # TODO: Implement config file loading if needed
        pass
    
    def validate(self) -> list[str]:
        """Validate configuration and return list of errors"""
        errors = []
        
        if not self.telegram.bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required")
        
        if not self.telegram.chat_id:
            errors.append("TELEGRAM_CHAT_ID is required")
        
        if self.storage.save_ml_frames and not self.storage.ml_frames_path:
            errors.append("ML_FRAMES_PATH is required when SAVE_ML_FRAMES=true")
        
        if self.alert.output_format not in ["gif", "mp4"]:
            errors.append("ALERT_FORMAT must be 'gif' or 'mp4'")
        
        return errors
    
    def get_frames_path(self) -> Path:
        """Get the full path for storing frames"""
        return Path(self.storage.base_path) / self.storage.frames_subdir
    
    def get_archives_path(self) -> Path:
        """Get the full path for storing archives"""
        return Path(self.storage.base_path) / self.storage.archives_subdir
    
    def get_database_path(self) -> Path:
        """Get the full path for the SQLite database"""
        return Path(self.storage.base_path) / self.storage.database_file
    
    def get_ml_frames_path(self) -> Optional[Path]:
        """Get the path for ML training frames if enabled"""
        if self.storage.save_ml_frames and self.storage.ml_frames_path:
            return Path(self.storage.ml_frames_path)
        return None


# Global config instance
config = Config()
