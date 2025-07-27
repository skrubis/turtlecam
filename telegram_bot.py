"""
TurtleCam Telegram Bot
Handles Telegram commands and sends motion alerts.
"""

import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import os

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError, RetryAfter

from config import config
from database import db
from gif_builder import AlertBuilder
from motion_detector import MotionDetector

logger = logging.getLogger(__name__)


class TurtleCamBot:
    """Telegram bot for turtle monitoring commands and alerts"""
    
    def __init__(self):
        self.bot = None
        self.application = None
        self.alert_builder = AlertBuilder()
        self.last_message_time = 0
        
        # Initialize bot
        self._setup_bot()
    
    def _setup_bot(self):
        """Initialize Telegram bot application"""
        if not config.telegram.bot_token:
            raise ValueError("TELEGRAM_BOT_TOKEN is required")
        
        self.application = Application.builder().token(config.telegram.bot_token).build()
        self.bot = self.application.bot
        
        # Add command handlers
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("photo", self.photo_command))
        self.application.add_handler(CommandHandler("gif", self.gif_command))
        self.application.add_handler(CommandHandler("stats", self.stats_command))
        self.application.add_handler(CommandHandler("status", self.status_command))
        
        logger.info("Telegram bot initialized")
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show available commands"""
        help_text = """
🐢 **TurtleCam Commands**

/photo - Capture and send a full-resolution still image
/gif [N] - Create GIF from last N frames (default: 10)
/stats - Show detection statistics
/status - Show system status
/help - Show this help message

The bot will automatically send motion alerts when your turtle is active!
        """
        
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def photo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Capture and send a still photo"""
        try:
            await update.message.reply_text("📸 Capturing photo...")
            
            # Import here to avoid circular imports
            from picamera2 import Picamera2
            
            # Capture photo
            camera = Picamera2()
            still_config = camera.create_still_configuration(
                main={
                    "size": (config.camera.full_res_width, config.camera.full_res_height),
                    "format": "RGB888"
                }
            )
            camera.configure(still_config)
            camera.start()
            
            # Capture and save
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            photo_path = Path(f"/tmp/turtle_photo_{timestamp}.jpg")
            camera.capture_file(str(photo_path))
            camera.stop()
            
            # Send photo
            with open(photo_path, 'rb') as photo_file:
                await context.bot.send_photo(
                    chat_id=config.telegram.chat_id,
                    photo=photo_file,
                    caption=f"📸 Turtle photo - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            
            # Cleanup
            photo_path.unlink(missing_ok=True)
            
        except Exception as e:
            logger.error(f"Failed to capture photo: {e}")
            await update.message.reply_text(f"❌ Failed to capture photo: {str(e)}")
    
    async def gif_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Create and send GIF from recent frames"""
        try:
            # Parse frame count from command
            frame_count = 10  # default
            if context.args and len(context.args) > 0:
                try:
                    frame_count = int(context.args[0])
                    frame_count = max(1, min(frame_count, config.alert.max_frames))
                except ValueError:
                    await update.message.reply_text("❌ Invalid frame count. Using default (10).")
            
            await update.message.reply_text(f"🎬 Creating {config.alert.output_format.upper()} from last {frame_count} frames...")
            
            # Build alert
            output_path = self.alert_builder.build_from_recent_frames(frame_count)
            
            if output_path and output_path.exists():
                # Send the file
                with open(output_path, 'rb') as alert_file:
                    if config.alert.output_format == "gif":
                        await context.bot.send_animation(
                            chat_id=config.telegram.chat_id,
                            animation=alert_file,
                            caption=f"🐢 Recent activity ({frame_count} frames)"
                        )
                    else:
                        await context.bot.send_video(
                            chat_id=config.telegram.chat_id,
                            video=alert_file,
                            caption=f"🐢 Recent activity ({frame_count} frames)"
                        )
                
                # Cleanup
                output_path.unlink(missing_ok=True)
            else:
                await update.message.reply_text("❌ No recent frames available for alert creation.")
                
        except Exception as e:
            logger.error(f"Failed to create GIF: {e}")
            await update.message.reply_text(f"❌ Failed to create alert: {str(e)}")
    
    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show detection statistics"""
        try:
            stats = db.get_stats()
            
            stats_text = f"""
📊 **Detection Statistics**

Total detections: {stats.get('total_detections', 0)}
Today's detections: {stats.get('today_detections', 0)}
First detection: {stats.get('first_detection', 'None')}
Last detection: {stats.get('last_detection', 'None')}

🎯 Current settings:
- Motion threshold: {config.motion.motion_threshold}
- Inactivity timeout: {config.motion.inactivity_timeout}s
- Alert format: {config.alert.output_format.upper()}
- Alert FPS: {config.alert.target_fps}
            """
            
            await update.message.reply_text(stats_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            await update.message.reply_text(f"❌ Failed to get statistics: {str(e)}")
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show system status"""
        try:
            import psutil
            import subprocess
            
            # System info
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage(config.storage.base_path)
            
            # Check if motion detection service is running
            try:
                result = subprocess.run(['systemctl', 'is-active', 'turtle_motion.service'], 
                                      capture_output=True, text=True)
                motion_status = "🟢 Running" if result.returncode == 0 else "🔴 Stopped"
            except:
                motion_status = "❓ Unknown"
            
            status_text = f"""
🖥️ **System Status**

Motion Detection: {motion_status}
CPU Usage: {cpu_percent:.1f}%
Memory Usage: {memory.percent:.1f}%
Disk Usage: {disk.percent:.1f}%

📁 Storage paths:
- Frames: {config.get_frames_path()}
- Database: {config.get_database_path()}
- ML Frames: {'Enabled' if config.storage.save_ml_frames else 'Disabled'}

⚙️ Camera settings:
- Preview: {config.camera.preview_width}x{config.camera.preview_height}
- Full-res: {config.camera.full_res_width}x{config.camera.full_res_height}
            """
            
            await update.message.reply_text(status_text, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            await update.message.reply_text(f"❌ Failed to get system status: {str(e)}")
    
    async def send_motion_alert(self, frames_count: int = None):
        """Send motion alert to Telegram"""
        try:
            # Rate limiting
            current_time = time.time()
            if current_time - self.last_message_time < config.telegram.rate_limit_delay:
                logger.debug("Rate limiting: skipping alert")
                return
            
            # Build alert
            output_path = self.alert_builder.build_from_recent_frames(frames_count or config.alert.max_frames)
            
            if not output_path or not output_path.exists():
                logger.error("Failed to create motion alert")
                return
            
            # Send alert with retry logic
            for attempt in range(config.telegram.max_retries):
                try:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    caption = f"🐢 Motion detected! {timestamp}"
                    
                    with open(output_path, 'rb') as alert_file:
                        if config.alert.output_format == "gif":
                            await self.bot.send_animation(
                                chat_id=config.telegram.chat_id,
                                animation=alert_file,
                                caption=caption
                            )
                        else:
                            await self.bot.send_video(
                                chat_id=config.telegram.chat_id,
                                video=alert_file,
                                caption=caption
                            )
                    
                    self.last_message_time = current_time
                    logger.info(f"Motion alert sent successfully")
                    break
                    
                except RetryAfter as e:
                    wait_time = e.retry_after
                    logger.warning(f"Rate limited by Telegram, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    
                except TelegramError as e:
                    logger.error(f"Telegram error (attempt {attempt + 1}): {e}")
                    if attempt < config.telegram.max_retries - 1:
                        await asyncio.sleep(config.telegram.retry_backoff ** attempt)
                    else:
                        logger.error("Failed to send alert after all retries")
            
            # Cleanup
            output_path.unlink(missing_ok=True)
            
        except Exception as e:
            logger.error(f"Failed to send motion alert: {e}")
    
    async def start_polling(self):
        """Start the bot with polling"""
        logger.info("Starting Telegram bot polling")
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received interrupt signal")
        finally:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
    
    def run(self):
        """Run the bot"""
        asyncio.run(self.start_polling())


async def send_motion_alert_standalone():
    """Standalone function to send motion alert (for systemd service)"""
    try:
        bot = TurtleCamBot()
        await bot.send_motion_alert()
    except Exception as e:
        logger.error(f"Failed to send standalone motion alert: {e}")


def main():
    """Main entry point for Telegram bot service"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="TurtleCam Telegram Bot")
    parser.add_argument("--alert", action="store_true", help="Send motion alert and exit")
    parser.add_argument("--frames", type=int, help="Number of frames for alert")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, config.system.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('/var/log/turtle/bot.log')
        ]
    )
    
    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error(f"Configuration errors: {errors}")
        sys.exit(1)
    
    try:
        if args.alert:
            # Send single alert and exit
            asyncio.run(send_motion_alert_standalone())
        else:
            # Run bot continuously
            bot = TurtleCamBot()
            bot.run()
            
    except Exception as e:
        logger.error(f"Bot error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
