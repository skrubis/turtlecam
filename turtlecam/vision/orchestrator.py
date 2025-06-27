"""Vision orchestrator for TurtleCam.

This module orchestrates the vision pipeline components (camera, motion detector,
crop store, and GIF builder) to create a complete motion detection and recording system.
"""

import os
import time
import logging
import threading
import queue
import json
from datetime import datetime
from pathlib import Path

from .camera import Camera
from .motion_detector import MotionDetector
from .crop_store import CropStore
from .gif_builder import GIFBuilder

logger = logging.getLogger(__name__)


class VisionOrchestrator:
    """Orchestrates the vision pipeline components.
    
    Manages the flow of data between the camera, motion detector,
    crop store, and GIF builder to detect motion and create GIFs.
    """
    
    def __init__(self, 
                 config=None,
                 inactivity_timeout=8,
                 mock_mode=False):
        """Initialize the vision orchestrator.
        
        Args:
            config (dict): Configuration dictionary
            inactivity_timeout (int): Seconds of inactivity before creating GIF
            mock_mode (bool): Whether to use mock components for testing
        """
        self.config = config or {}
        self.inactivity_timeout = inactivity_timeout
        self.mock_mode = mock_mode
        
        # Thread control
        self.running = False
        self.lock = threading.RLock()
        
        # State variables
        self.motion_active = False
        self.last_motion_time = None
        
        # Initialize components
        self._init_components()
        
        # Queue for image processing tasks
        self.process_queue = queue.Queue(maxsize=100)
        
        # Create the processing thread
        self.process_thread = None
        
    def _init_components(self):
        """Initialize vision pipeline components."""
        # Extract component config
        camera_config = self.config.get('camera', {})
        motion_config = self.config.get('motion', {})
        crop_config = self.config.get('crop_store', {})
        gif_config = self.config.get('gif', {})
        
        # Initialize camera
        preview_size = camera_config.get('preview_size', (640, 480))
        crop_size = camera_config.get('crop_size', (1920, 1920))
        fps = camera_config.get('fps', 8)
        
        self.camera = Camera(
            preview_size=preview_size,
            crop_size=crop_size,
            fps=fps,
            mock_mode=self.mock_mode
        )
        
        # Initialize motion detector
        min_area = motion_config.get('min_area', 800)
        history = motion_config.get('history', 500)
        var_threshold = motion_config.get('var_threshold', 16)
        detect_shadows = motion_config.get('detect_shadows', True)
        
        self.motion_detector = MotionDetector(
            min_area=min_area,
            history=history,
            var_threshold=var_threshold,
            detect_shadows=detect_shadows
        )
        
        # Initialize crop store
        base_dir = crop_config.get('base_dir', 'data/crops')
        db_path = crop_config.get('db_path', 'data/turtlecam.db')
        max_age_days = crop_config.get('max_age_days', 30)
        max_disk_percent = crop_config.get('max_disk_percent', 80)
        
        self.crop_store = CropStore(
            base_dir=base_dir,
            db_path=db_path,
            max_age_days=max_age_days,
            max_disk_percent=max_disk_percent
        )
        
        # Initialize GIF builder
        max_width = gif_config.get('max_width', 1920)
        max_frames = gif_config.get('max_frames', 20)
        gif_fps = gif_config.get('gif_fps', 4)
        output_dir = gif_config.get('output_dir', 'data/gifs')
        
        self.gif_builder = GIFBuilder(
            max_width=max_width,
            max_frames=max_frames,
            gif_fps=gif_fps,
            output_dir=output_dir
        )
        
    def start(self):
        """Start the vision orchestrator."""
        with self.lock:
            if self.running:
                logger.warning("Vision orchestrator already running")
                return
            
            # Start the camera
            self.camera.start()
            
            # Create and start the processing thread
            self.running = True
            self.process_thread = threading.Thread(target=self._processing_loop)
            self.process_thread.daemon = True
            self.process_thread.start()
            
            logger.info("Vision orchestrator started")
    
    def stop(self):
        """Stop the vision orchestrator."""
        with self.lock:
            if not self.running:
                return
                
            self.running = False
            
            # Wait for processing thread to finish
            if self.process_thread and self.process_thread.is_alive():
                self.process_thread.join(timeout=5.0)
            
            # Stop the camera
            self.camera.stop()
            
            logger.info("Vision orchestrator stopped")
    
    def _processing_loop(self):
        """Main processing loop for the vision pipeline."""
        try:
            last_cleanup_time = time.time()
            
            while self.running:
                # Get latest frame from camera
                frame = self.camera.get_frame()
                if frame is None:
                    # No frame available, wait and try again
                    time.sleep(0.1)
                    continue
                
                # Run motion detection
                motion_detected, bbox, mask = self.motion_detector.detect(frame)
                
                # Handle motion detection
                if motion_detected:
                    # Update state
                    self.last_motion_time = time.time()
                    
                    # If this is a new motion event, log it
                    if not self.motion_active:
                        logger.info("Motion started")
                        self.motion_active = True
                    
                    # Capture high-res crop
                    self._handle_motion_detection(frame, bbox)
                else:
                    # Check if we need to finish a motion sequence
                    if self.motion_active and self.last_motion_time:
                        elapsed = time.time() - self.last_motion_time
                        
                        if elapsed >= self.inactivity_timeout:
                            logger.info(f"Motion stopped (inactive for {elapsed:.1f}s)")
                            self._handle_motion_end()
                
                # Perform occasional maintenance
                if time.time() - last_cleanup_time > 3600:  # Once per hour
                    self._perform_maintenance()
                    last_cleanup_time = time.time()
                    
                # Brief sleep to prevent CPU hogging
                time.sleep(0.01)
                
        except Exception as e:
            logger.error(f"Error in vision processing loop: {e}", exc_info=True)
        finally:
            logger.info("Vision processing loop ended")
    
    def _handle_motion_detection(self, frame, bbox):
        """Handle motion detection by capturing a high-res crop.
        
        Args:
            frame (numpy.ndarray): Current frame
            bbox (tuple): Bounding box (x, y, w, h)
        """
        try:
            timestamp = datetime.now()
            
            # Generate path for this crop
            crop_path = self.crop_store.get_crop_path(timestamp)
            
            # Capture high-res crop (asynchronous)
            self.process_queue.put({
                'action': 'capture_crop',
                'bbox': bbox,
                'timestamp': timestamp,
                'path': crop_path
            })
            
        except Exception as e:
            logger.error(f"Error handling motion detection: {e}")
    
    def _handle_motion_end(self):
        """Handle the end of a motion sequence by creating a GIF."""
        try:
            self.motion_active = False
            
            # Get latest crops
            latest_crops = self.crop_store.get_latest_crops(limit=self.gif_builder.max_frames)
            
            if not latest_crops:
                logger.warning("No crops available for GIF")
                return
                
            # Add crops to GIF builder
            for crop in latest_crops:
                self.gif_builder.add_frame(
                    crop['img_path'],
                    bbox=(crop['bbox_x'], crop['bbox_y'], crop['bbox_w'], crop['bbox_h']),
                    timestamp=datetime.fromisoformat(crop['ts'])
                )
            
            # Create GIF
            gif_path = self.gif_builder.create_gif()
            
            if gif_path:
                logger.info(f"Created motion GIF: {gif_path}")
                
                # Notify via Telegram (will be implemented in the next module)
                self._notify_motion(gif_path)
            
        except Exception as e:
            logger.error(f"Error handling motion end: {e}")
    
    def _notify_motion(self, gif_path):
        """Notify about motion via Telegram.
        
        This is a placeholder that will be implemented when we integrate
        with the Telegram bot module.
        
        Args:
            gif_path (str): Path to the motion GIF
        """
        # This will be connected to the Telegram module later
        logger.info(f"[PLACEHOLDER] Would send GIF to Telegram: {gif_path}")
    
    def _perform_maintenance(self):
        """Perform maintenance tasks (archiving, cleanup)."""
        try:
            # Archive old crops
            archived_count = self.crop_store.archive_old_crops()
            if archived_count > 0:
                logger.info(f"Archived {archived_count} old crop files")
            
            # Cleanup old data if needed
            removed_count = self.crop_store.cleanup_old_data()
            if removed_count > 0:
                logger.info(f"Removed {removed_count} old archives")
                
        except Exception as e:
            logger.error(f"Error performing maintenance: {e}")
    
    def force_capture(self):
        """Force capture a photo without motion detection.
        
        Returns:
            str: Path to captured image
        """
        try:
            # Get current frame
            frame = self.camera.get_frame()
            if frame is None:
                logger.error("No frame available for forced capture")
                return None
            
            # Generate path for this photo
            timestamp = datetime.now()
            photo_path = self.crop_store.get_crop_path(timestamp)
            
            # Capture full-frame photo
            success = self.camera.capture_high_res_crop(
                bbox=(0, 0, self.camera.preview_size[0], self.camera.preview_size[1]),
                output_path=photo_path
            )
            
            if success:
                logger.info(f"Forced photo capture: {photo_path}")
                return str(photo_path)
            else:
                logger.error("Failed to capture forced photo")
                return None
                
        except Exception as e:
            logger.error(f"Error in force capture: {e}")
            return None
    
    def force_gif(self, num_frames=10):
        """Force creation of a GIF from recent frames.
        
        Args:
            num_frames (int): Number of frames to include in GIF
            
        Returns:
            str: Path to created GIF or None if failed
        """
        try:
            # Get latest crops
            latest_crops = self.crop_store.get_latest_crops(limit=num_frames)
            
            if not latest_crops:
                logger.warning("No crops available for forced GIF")
                return None
                
            # Clear GIF builder buffer
            self.gif_builder.clear_buffer()
            
            # Add crops to GIF builder
            for crop in latest_crops:
                self.gif_builder.add_frame(
                    crop['img_path'],
                    bbox=(crop['bbox_x'], crop['bbox_y'], crop['bbox_w'], crop['bbox_h']),
                    timestamp=datetime.fromisoformat(crop['ts'])
                )
            
            # Create GIF with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            gif_path = self.gif_builder.create_gif(
                output_path=Path(self.gif_builder.output_dir) / f"manual_{timestamp}.gif"
            )
            
            if gif_path:
                logger.info(f"Created forced GIF: {gif_path}")
                return gif_path
            
            return None
                
        except Exception as e:
            logger.error(f"Error in force GIF: {e}")
            return None
