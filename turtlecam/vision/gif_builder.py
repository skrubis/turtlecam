"""GIF builder module for TurtleCam.

This module handles creating animated GIFs from captured frames for Telegram alerts.
"""

import os
import time
import logging
import json
from datetime import datetime
from pathlib import Path
import imageio
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


class GIFBuilder:
    """Creates animated GIFs from captured frames for Telegram alerts."""
    
    def __init__(self, 
                 max_width=1920,
                 max_frames=20,
                 gif_fps=4,
                 timestamp_format="%Y-%m-%d %H:%M:%S",
                 output_dir="data/gifs"):
        """Initialize the GIF Builder.
        
        Args:
            max_width (int): Maximum width of output GIF
            max_frames (int): Maximum number of frames to include
            gif_fps (int): Frames per second in output GIF
            timestamp_format (str): Format string for timestamp overlay
            output_dir (str): Directory to save GIFs
        """
        self.max_width = max_width
        self.max_frames = max_frames
        self.gif_fps = gif_fps
        self.timestamp_format = timestamp_format
        self.output_dir = Path(output_dir)
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # In-memory frame buffer for the current collection
        self.frame_buffer = []
        self.metadata_buffer = []
        
    def add_frame(self, image_path, bbox=None, timestamp=None):
        """Add a frame to the current buffer.
        
        Args:
            image_path (str or Path): Path to the image file
            bbox (tuple): Optional bounding box (x, y, w, h) for highlighting
            timestamp (datetime): Timestamp for the frame, defaults to now
            
        Returns:
            bool: True if successfully added
        """
        try:
            # Record metadata for this frame
            if timestamp is None:
                timestamp = datetime.now()
                
            metadata = {
                "path": str(image_path),
                "timestamp": timestamp.isoformat(),
                "bbox": bbox
            }
            
            self.frame_buffer.append(str(image_path))
            self.metadata_buffer.append(metadata)
            
            # Limit buffer size
            if len(self.frame_buffer) > self.max_frames:
                self.frame_buffer.pop(0)
                self.metadata_buffer.pop(0)
                
            return True
            
        except Exception as e:
            logger.error(f"Error adding frame to buffer: {e}")
            return False
    
    def create_gif(self, output_path=None, add_timestamp=True, add_bbox=True):
        """Create a GIF from the current frame buffer.
        
        Args:
            output_path (str or Path, optional): Output GIF path. If None, auto-generate.
            add_timestamp (bool): Whether to overlay timestamp
            add_bbox (bool): Whether to overlay bounding box
            
        Returns:
            str or None: Path to the created GIF, or None on failure
        """
        if not self.frame_buffer:
            logger.warning("No frames in buffer to create GIF")
            return None
            
        if output_path is None:
            # Generate output filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.output_dir / f"motion_{timestamp}.gif"
        else:
            output_path = Path(output_path)
            
        try:
            # Make sure output directory exists
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Process frames
            processed_frames = []
            
            for idx, (image_path, metadata) in enumerate(zip(self.frame_buffer, self.metadata_buffer)):
                # Open image with PIL
                img = Image.open(image_path)
                
                # Resize if necessary while preserving aspect ratio
                if img.width > self.max_width:
                    ratio = self.max_width / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((self.max_width, new_height), Image.Resampling.LANCZOS)
                
                # Add timestamp overlay
                if add_timestamp and "timestamp" in metadata:
                    try:
                        timestamp_obj = datetime.fromisoformat(metadata["timestamp"])
                        timestamp_str = timestamp_obj.strftime(self.timestamp_format)
                        
                        draw = ImageDraw.Draw(img)
                        # Try to get a font, fall back to default if not found
                        try:
                            font = ImageFont.truetype("DejaVuSans.ttf", 20)
                        except IOError:
                            font = ImageFont.load_default()
                            
                        # Draw text with shadow
                        draw.text((11, 11), timestamp_str, fill=(0, 0, 0), font=font)
                        draw.text((10, 10), timestamp_str, fill=(255, 255, 255), font=font)
                    except Exception as e:
                        logger.warning(f"Error adding timestamp: {e}")
                
                # Add bounding box overlay
                if add_bbox and "bbox" in metadata and metadata["bbox"]:
                    try:
                        x, y, w, h = metadata["bbox"]
                        # Scale bbox if we resized the image
                        if img.width != self.max_width and img.width != self.max_width:
                            ratio = img.width / self.max_width
                            x = int(x * ratio)
                            y = int(y * ratio) 
                            w = int(w * ratio)
                            h = int(h * ratio)
                            
                        draw = ImageDraw.Draw(img)
                        
                        # Draw rectangle
                        draw.rectangle(
                            [(x, y), (x + w, y + h)],
                            outline=(255, 0, 0),
                            width=3
                        )
                    except Exception as e:
                        logger.warning(f"Error adding bounding box: {e}")
                
                # Convert PIL Image to numpy array for imageio
                processed_frames.append(img)
            
            # Create GIF using imageio
            imageio.mimsave(
                output_path,
                processed_frames,
                duration=1.0/self.gif_fps,
                loop=0  # 0 means loop indefinitely
            )
            
            # Save metadata alongside the GIF
            metadata_path = output_path.with_suffix('.json')
            with open(metadata_path, 'w') as f:
                json.dump({
                    "created": datetime.now().isoformat(),
                    "frames": self.metadata_buffer,
                    "fps": self.gif_fps,
                    "frame_count": len(processed_frames)
                }, f, indent=2)
            
            logger.info(f"Created GIF with {len(processed_frames)} frames: {output_path}")
            return str(output_path)
            
        except Exception as e:
            logger.error(f"Error creating GIF: {e}")
            return None
    
    def clear_buffer(self):
        """Clear the current frame buffer."""
        self.frame_buffer.clear()
        self.metadata_buffer.clear()
        
    def get_buffer_size(self):
        """Get the number of frames in buffer.
        
        Returns:
            int: Number of frames in buffer
        """
        return len(self.frame_buffer)
