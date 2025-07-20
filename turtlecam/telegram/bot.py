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
        # Ensure chat_id is an integer if it's a number, to support group chats
        try:
            self.chat_id = int(chat_id) if chat_id and chat_id.strip() else None
            logger.info(f"Telegram chat ID set to: {self.chat_id}")
        except (ValueError, TypeError):
            logger.error(f"Invalid TELEGRAM_CHAT_ID: {chat_id}. It must be a number.")
            self.chat_id = None

        self.vision_orchestrator = vision_orchestrator
        self.env_monitor = env_monitor
        self.relay_controller = relay_controller

        # Initialize application and bot instance
        self.application = Application.builder().token(self.token).build()
        self.bot = self.application.bot

        self._setup_handlers()
        
        # Command handlers dictionary for easy help generation
        self.command_descriptions = {
            "start": "Begin interaction with the bot",
            "help": "Show available commands",
            "status": "Show current temperature, humidity and relay states",
            "photo": "Take and send an instant photo",
            "gif": "Create and send a GIF from recent frames",
            "relay": "Control relays (usage: /relay <name> on|off)",
        }
        
        self.running = False
        
    def _setup_handlers(self):
        """Set up command handlers for the bot."""
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
        """Log Errors caused by Updates."""
        logger.error(
            'Update "%s" caused error "%s"',
            update,
            context.error,
            exc_info=context.error
        )
        
    def start(self):
        """Start the Telegram bot."""
        if self.application:
            # Start the bot in a new thread
            logger.info("Starting Telegram bot")
            self.running = True
            self.application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    def stop(self):
        """Stop the Telegram bot."""
        logger.info("Stopping Telegram bot")
        if self.application and self.running:
            # Run the async stop method in a blocking way
            asyncio.run(self.application.stop())
            self.running = False
            
    async def _send_file(self, file_path: str, caption: str, chat_id: Optional[str], method: Callable, file_kwarg_name: str) -> bool:
        """Generic method to send a file (photo or GIF)."""
        chat_id = chat_id or self.chat_id
        if not chat_id:
            logger.error(f"Cannot send file, no chat_id specified for {method.__name__}")
            return False

        try:
            with open(file_path, 'rb') as file_content:
                kwargs = {
                    'chat_id': chat_id,
                    file_kwarg_name: InputFile(file_content),
                    'caption': caption,
                }
                await method(**kwargs)
            return True
        except FileNotFoundError:
            logger.error(f"File not found for sending: {file_path}")
            return False
        except Exception as e:
            logger.error(f"Error sending file {file_path}: {e}", exc_info=True)
            return False

    async def send_photo(self, photo_path: str, caption: str = None, chat_id: str = None) -> bool:
        """Send a photo."""
        return await self._send_file(photo_path, caption, chat_id, self.bot.send_photo, 'photo')

    async def send_gif(self, gif_path: str, caption: str = None, chat_id: str = None) -> bool:
        """Send an animation (GIF)."""
        return await self._send_file(gif_path, caption, chat_id, self.bot.send_animation, 'animation')
    
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

    This provides a way to call async methods from synchronous code by using
    the bot's existing asyncio event loop.
    """

    def __init__(self, bot: TurtleBot):
        """Initialize with a TurtleBot instance."""
        self.bot = bot
        self.application = bot.application

    def _schedule_task(self, coro):
        """Schedule a coroutine on the bot's event loop."""
        if self.application and self.application.loop and self.application.loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self.application.loop)
        else:
            logger.warning("Telegram bot loop not running. Cannot schedule task.")

    def send_message(self, *args, **kwargs):
        """Schedule a message to be sent."""
        self._schedule_task(self.bot.application.bot.send_message(*args, **kwargs))

    def _send_file(self, file_type: str, *args, **kwargs):
        """Internal helper to schedule a file to be sent."""
        # Dynamically get the correct send method from the bot object
        # e.g., bot.send_photo, bot.send_animation
        send_method = getattr(self.bot.application.bot, f"send_{file_type}", None)
        if send_method and callable(send_method):
            self._schedule_task(send_method(*args, **kwargs))
        else:
            logger.error(f"Invalid file type specified: '{file_type}'. No such method on bot.")

    def send_photo(self, *args, **kwargs):
        """Send a photo."""
        self._send_file('photo', *args, **kwargs)

    def send_gif(self, *args, **kwargs):
        """Send an animation (GIF)."""
        self._send_file('animation', *args, **kwargs)

    def send_motion_alert(self, *args, **kwargs):
        """Send a motion alert with GIF."""
        self._schedule_task(self.bot.send_motion_alert(*args, **kwargs))

    def send_temperature_alert(self, *args, **kwargs):
        """Send a temperature alert."""
        self._schedule_task(self.bot.send_temperature_alert(*args, **kwargs))
        
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
