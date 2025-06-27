"""Telegram bot module for TurtleCam.

This module implements a Telegram bot for sending alerts and handling commands.
"""

import os
import logging
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from telegram import Update, Bot, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)


class TurtleBot:
    """Telegram bot for TurtleCam.
    
    Handles sending alerts to Telegram and processing commands from users.
    """
    
    def __init__(self, token: str, chat_id: str = None, vision_orchestrator=None, 
                 env_monitor=None, relay_controller=None):
        """Initialize the Telegram bot.
        
        Args:
            token (str): Telegram bot token
            chat_id (str, optional): Default chat ID for messages
            vision_orchestrator: Vision orchestrator for camera control
            env_monitor: Environmental monitor for temp/humidity readings
            relay_controller: Relay controller for light/heat control
        """
        self.token = token
        self.chat_id = chat_id
        self.vision_orchestrator = vision_orchestrator
        self.env_monitor = env_monitor
        self.relay_controller = relay_controller
        
        # Initialize application
        self.application = None
        self._setup_handlers()
        
        # Bot instance for non-handler methods
        self.bot = Bot(token=self.token)
        
        # Command handlers dictionary for easy help generation
        self.command_descriptions = {
            "start": "Begin interaction with the bot",
            "help": "Show available commands",
            "status": "Show current temperature, humidity and relay states",
            "photo": "Take and send an instant photo",
            "gif": "Create and send a GIF from recent frames",
            "relay": "Control relays (usage: /relay <name> on|off)",
        }
        
    def _setup_handlers(self):
        """Set up command handlers for the bot."""
        self.application = Application.builder().token(self.token).build()
        
        # Add command handlers
        self.application.add_handler(CommandHandler("start", self._start_command))
        self.application.add_handler(CommandHandler("help", self._help_command))
        self.application.add_handler(CommandHandler("status", self._status_command))
        self.application.add_handler(CommandHandler("photo", self._photo_command))
        self.application.add_handler(CommandHandler("gif", self._gif_command))
        self.application.add_handler(CommandHandler("relay", self._relay_command))
        
        # Add fallback handler for unknown commands
        self.application.add_handler(MessageHandler(
            filters.COMMAND, self._unknown_command
        ))
        
        # Add error handler
        self.application.add_error_handler(self._error_handler)
    
    async def _start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /start command."""
        message = (
            "🐢 *TurtleCam Bot* 🐢\n\n"
            "Welcome to TurtleCam, your smart turtle terrarium controller!\n\n"
            "Use /help to see available commands."
        )
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)
        
    async def _help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command."""
        help_text = "🐢 *TurtleCam Bot Commands* 🐢\n\n"
        
        # Add each command and its description
        for cmd, desc in self.command_descriptions.items():
            help_text += f"/{cmd} - {desc}\n"
            
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
        
    async def _status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /status command."""
        status_parts = ["🐢 *TurtleCam Status* 🐢\n\n"]
        
        # Add environmental data if available
        if self.env_monitor:
            try:
                temp = self.env_monitor.get_temperature()
                humidity = self.env_monitor.get_humidity()
                
                if temp is not None and humidity is not None:
                    status_parts.append(f"🌡️ *Temperature*: {temp:.1f} °C")
                    status_parts.append(f"💧 *Humidity*: {humidity:.1f} %")
                else:
                    status_parts.append("⚠️ Environmental data not available")
            except Exception as e:
                logger.error(f"Error getting environmental data: {e}")
                status_parts.append("⚠️ Error getting environmental data")
        else:
            status_parts.append("⚠️ Environmental monitor not available")
            
        # Add relay status if available
        if self.relay_controller:
            try:
                relay_states = self.relay_controller.get_all_states()
                
                status_parts.append("\n*Relay States:*")
                for name, state in relay_states.items():
                    icon = "🟢" if state else "🔴"
                    status_parts.append(f"{icon} *{name}*: {'ON' if state else 'OFF'}")
            except Exception as e:
                logger.error(f"Error getting relay states: {e}")
                status_parts.append("⚠️ Error getting relay states")
        else:
            status_parts.append("⚠️ Relay controller not available")
            
        # Send the status message
        status_message = "\n".join(status_parts)
        await update.message.reply_text(status_message, parse_mode=ParseMode.MARKDOWN)
        
    async def _photo_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /photo command."""
        if not self.vision_orchestrator:
            await update.message.reply_text("⚠️ Camera not available")
            return
            
        await update.message.reply_text("📸 Taking a photo...")
        
        try:
            # Capture photo
            photo_path = self.vision_orchestrator.force_capture()
            
            if photo_path:
                # Send photo back to user
                with open(photo_path, 'rb') as photo_file:
                    await update.message.reply_photo(photo_file)
            else:
                await update.message.reply_text("❌ Failed to capture photo")
                
        except Exception as e:
            logger.error(f"Error handling photo command: {e}")
            await update.message.reply_text("❌ Error capturing photo")
        
    async def _gif_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /gif command."""
        if not self.vision_orchestrator:
            await update.message.reply_text("⚠️ Camera not available")
            return
        
        # Parse number of frames from command
        num_frames = 10  # Default
        if context.args and len(context.args) > 0:
            try:
                num_frames = int(context.args[0])
                num_frames = max(1, min(num_frames, 30))  # Bound between 1-30
            except ValueError:
                await update.message.reply_text("⚠️ Invalid number format. Using default (10).")
        
        await update.message.reply_text(f"🎬 Creating GIF with {num_frames} frames...")
        
        try:
            # Create GIF
            gif_path = self.vision_orchestrator.force_gif(num_frames=num_frames)
            
            if gif_path:
                # Send GIF back to user
                with open(gif_path, 'rb') as gif_file:
                    await update.message.reply_animation(gif_file)
            else:
                await update.message.reply_text("❌ Failed to create GIF")
                
        except Exception as e:
            logger.error(f"Error handling GIF command: {e}")
            await update.message.reply_text("❌ Error creating GIF")
        
    async def _relay_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /relay command."""
        if not self.relay_controller:
            await update.message.reply_text("⚠️ Relay controller not available")
            return
            
        # Check if we have the required arguments
        if not context.args or len(context.args) < 2:
            await update.message.reply_text(
                "⚠️ Invalid format. Use: `/relay <name> on|off`",
                parse_mode=ParseMode.MARKDOWN
            )
            return
            
        relay_name = context.args[0].lower()
        action = context.args[1].lower()
        
        if action not in ["on", "off"]:
            await update.message.reply_text("⚠️ Action must be 'on' or 'off'")
            return
            
        try:
            # Set relay state
            success = self.relay_controller.set_relay(
                relay_name, state=(action == "on")
            )
            
            if success:
                await update.message.reply_text(
                    f"✅ Set relay *{relay_name}* to *{action.upper()}*",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(f"❌ Unknown relay: *{relay_name}*", 
                                              parse_mode=ParseMode.MARKDOWN)
                
        except Exception as e:
            logger.error(f"Error handling relay command: {e}")
            await update.message.reply_text("❌ Error controlling relay")
        
    async def _unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle unknown commands."""
        await update.message.reply_text(
            "Unknown command. Use /help to see available commands."
        )
        
    async def _error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors in the telegram bot."""
        logger.error(f"Telegram error: {context.error}")
        
    def start(self):
        """Start the Telegram bot."""
        if self.application:
            # Start the bot in a new thread
            logger.info("Starting Telegram bot")
            self.application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    def stop(self):
        """Stop the Telegram bot."""
        if self.application:
            logger.info("Stopping Telegram bot")
            self.application.stop()
            
    async def send_message(self, text: str, chat_id: str = None, parse_mode: str = None):
        """Send a text message.
        
        Args:
            text (str): Message text
            chat_id (str, optional): Chat ID, defaults to self.chat_id
            parse_mode (str, optional): Parse mode (HTML, Markdown)
            
        Returns:
            bool: True if successful
        """
        if not chat_id:
            chat_id = self.chat_id
            
        if not chat_id:
            logger.error("No chat ID available for sending message")
            return False
            
        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False
    
    async def send_photo(self, photo_path: str, caption: str = None, chat_id: str = None):
        """Send a photo.
        
        Args:
            photo_path (str): Path to the photo file
            caption (str, optional): Photo caption
            chat_id (str, optional): Chat ID, defaults to self.chat_id
            
        Returns:
            bool: True if successful
        """
        if not chat_id:
            chat_id = self.chat_id
            
        if not chat_id:
            logger.error("No chat ID available for sending photo")
            return False
            
        try:
            with open(photo_path, 'rb') as photo_file:
                await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(photo_file),
                    caption=caption
                )
            return True
        except Exception as e:
            logger.error(f"Error sending photo: {e}")
            return False
    
    async def send_gif(self, gif_path: str, caption: str = None, chat_id: str = None):
        """Send an animation (GIF).
        
        Args:
            gif_path (str): Path to the GIF file
            caption (str, optional): GIF caption
            chat_id (str, optional): Chat ID, defaults to self.chat_id
            
        Returns:
            bool: True if successful
        """
        if not chat_id:
            chat_id = self.chat_id
            
        if not chat_id:
            logger.error("No chat ID available for sending GIF")
            return False
            
        try:
            with open(gif_path, 'rb') as gif_file:
                await self.bot.send_animation(
                    chat_id=chat_id,
                    animation=InputFile(gif_file),
                    caption=caption
                )
            return True
        except Exception as e:
            logger.error(f"Error sending GIF: {e}")
            return False
    
    async def send_motion_alert(self, gif_path: str):
        """Send a motion alert with GIF.
        
        Args:
            gif_path (str): Path to the motion GIF
            
        Returns:
            bool: True if successful
        """
        caption = f"🐢 Motion detected at {datetime.now().strftime('%H:%M:%S')}"
        return await self.send_gif(gif_path, caption=caption)
    
    async def send_temperature_alert(self, temperature: float, threshold_type: str):
        """Send a temperature alert.
        
        Args:
            temperature (float): Current temperature
            threshold_type (str): "high" or "low"
            
        Returns:
            bool: True if successful
        """
        icon = "🔥" if threshold_type == "high" else "❄️"
        message = (
            f"{icon} *Temperature Alert* {icon}\n\n"
            f"Current temperature: *{temperature:.1f} °C*\n"
            f"Status: {'TOO HOT' if threshold_type == 'high' else 'TOO COLD'}"
        )
        return await self.send_message(message, parse_mode=ParseMode.MARKDOWN)


class AsyncTelegramSender:
    """Utility class for sending Telegram messages from non-async code.
    
    This provides a way to call async methods from synchronous code.
    """
    
    def __init__(self, bot: TurtleBot):
        """Initialize with a TurtleBot instance."""
        self.bot = bot
        self.loop = asyncio.new_event_loop()
        
    def send_message(self, *args, **kwargs):
        """Send a text message."""
        asyncio.run_coroutine_threadsafe(
            self.bot.send_message(*args, **kwargs),
            self.loop
        )
        
    def send_photo(self, *args, **kwargs):
        """Send a photo."""
        asyncio.run_coroutine_threadsafe(
            self.bot.send_photo(*args, **kwargs),
            self.loop
        )
        
    def send_gif(self, *args, **kwargs):
        """Send an animation (GIF)."""
        asyncio.run_coroutine_threadsafe(
            self.bot.send_gif(*args, **kwargs),
            self.loop
        )
        
    def send_motion_alert(self, *args, **kwargs):
        """Send a motion alert with GIF."""
        asyncio.run_coroutine_threadsafe(
            self.bot.send_motion_alert(*args, **kwargs),
            self.loop
        )
        
    def send_temperature_alert(self, *args, **kwargs):
        """Send a temperature alert."""
        asyncio.run_coroutine_threadsafe(
            self.bot.send_temperature_alert(*args, **kwargs),
            self.loop
        )
        
    def start_loop(self):
        """Start the async event loop in a thread."""
        def run_loop():
            asyncio.set_event_loop(self.loop)
            self.loop.run_forever()
            
        import threading
        self.thread = threading.Thread(target=run_loop, daemon=True)
        self.thread.start()
        
    def stop_loop(self):
        """Stop the async event loop."""
        self.loop.call_soon_threadsafe(self.loop.stop)
        
def create_dot_env_template():
    """Create a .env.example template file for bot configuration."""
    template_content = """# TurtleCam Telegram Bot Configuration
# Rename this file to .env and fill in your actual values

# Telegram Bot Token (get from @BotFather)
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Default Chat ID for sending alerts
# You can get this by sending /start to @userinfobot
TELEGRAM_CHAT_ID=your_chat_id_here
"""

    # Write the template file
    with open(".env.example", "w") as f:
        f.write(template_content)
        
    logger.info("Created .env.example template file")
