"""
TurtleCam Motion Detection
Background subtraction-based motion detection optimized for Hermann's tortoise behavior.
"""

import cv2
import numpy as np
import logging
import time
from datetime import datetime
from typing import Optional, Tuple, List
from threading import Thread, Event
from queue import Queue, Empty
import json
from pathlib import Path

from picamera2 import Picamera2
from config import config
from database import db, Detection

logger = logging.getLogger(__name__)


class MotionFrame:
    """Container for a motion detection frame with metadata"""
    
    def __init__(self, timestamp: datetime, motion_frame: np.ndarray, 
                 bbox: Optional[Tuple[int, int, int, int]] = None,
                 high_res_crop: Optional[np.ndarray] = None):
        self.timestamp = timestamp
        self.motion_frame = motion_frame  # 4K frame used for motion detection
        self.bbox = bbox  # (x, y, w, h) in motion coordinates
        self.high_res_crop = high_res_crop  # Cropped section around motion
        self.confidence = 1.0


class MotionDetector:
    """Motion detection using background subtraction with morphological filtering"""
    
    def __init__(self):
        self.camera = None
        self.previous_frame = None  # Store previous still frame for comparison
        self.motion_frames = []
        self.last_motion_time = 0
        self.motion_event_active = False
        self.last_capture_time = 0
        # Initialize camera for still frame capture
        self._setup_camera()
    
    def _setup_camera(self):
        """Initialize Picamera2 with preview and full-res configurations"""
        try:
            self.camera = Picamera2()
            
            # Configure high-resolution stream for motion detection with memory optimization
            motion_config = self.camera.create_preview_configuration(
                main={
                    "size": (config.camera.motion_width, config.camera.motion_height),
                    "format": "RGB888"
                },
                buffer_count=2  # Minimize buffer count to reduce memory usage
            )
            
            self.camera.configure(motion_config)
            
            # Set manual focus for stable image capture
            # Autofocus was causing image corruption and digital noise
            try:
                self.camera.set_controls({
                    "AfMode": 0,  # Manual focus
                    "LensPosition": 3.0  # Focus distance (adjust as needed: 0.0=close, 10.0=far)
                })
                logger.info("Manual focus set (LensPosition=3.0)")
            except Exception as e:
                logger.warning(f"Could not set manual focus: {e}")
            
            logger.info(f"Camera configured: Ultra-high-res motion detection {config.camera.motion_width}x{config.camera.motion_height} @ {config.camera.motion_fps}fps")
            
        except Exception as e:
            if "Cannot allocate memory" in str(e):
                logger.error(f"Camera memory allocation failed. Try: sudo raspi-config -> Advanced -> Memory Split -> 128 or 256")
                logger.error(f"Or reduce resolution in config.py: motion_width/height")
            logger.error(f"Failed to setup camera: {e}")
            raise
    
    def _setup_background_subtractor(self):
        """Initialize background subtraction algorithm"""
        # Using MOG2 for better handling of slow-moving objects like tortoises
        self.background_subtractor = cv2.createBackgroundSubtractorMOG2(
            detectShadows=True,
            varThreshold=config.motion.motion_threshold,
            history=500  # Longer history for stable background
        )
        # Note: setLearningRate method name varies between OpenCV versions
        try:
            self.background_subtractor.setLearningRate(config.motion.background_learning_rate)
        except AttributeError:
            # Fallback for older OpenCV versions
            pass
        logger.info("Background subtractor initialized")
    
    def _is_frame_corrupted(self, frame: np.ndarray) -> bool:
        """Check if frame is corrupted or contains garbage data"""
        if frame is None or frame.size == 0:
            return True
            
        # Check for extreme values that indicate corruption
        mean_val = np.mean(frame)
        std_val = np.std(frame)
        
        # Corrupted frames often have extreme mean/std values
        if mean_val < 5 or mean_val > 250:  # Too dark or too bright
            return True
        if std_val < 1 or std_val > 100:    # Too uniform or too noisy
            return True
            
        # Check for stripe patterns (common in corruption)
        # Look for repeating patterns in rows
        if frame.shape[0] > 100:  # Only for reasonably sized frames
            row_sample = frame[frame.shape[0]//2, :]
            if len(np.unique(row_sample)) < 10:  # Too few unique values = stripes
                return True
                
        return False
    
    def _preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """Preprocess frame for motion detection (RGB to grayscale)"""
        try:
            # Convert to grayscale for motion detection
            gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            
            # Apply Gaussian blur to reduce noise (stronger for high-res)
            blurred = cv2.GaussianBlur(gray, (7, 7), 0)
            
            return blurred
        except Exception as e:
            logger.error(f"Frame preprocessing failed: {e}")
            return None
    
    def _compare_still_frames(self, current_frame: np.ndarray, previous_frame: np.ndarray) -> Tuple[bool, Optional[Tuple[int, int, int, int]]]:
        """Compare two still frames to detect significant motion (turtle movement)"""
        try:
            # Convert both frames to grayscale for comparison
            current_gray = cv2.cvtColor(current_frame, cv2.COLOR_RGB2GRAY)
            previous_gray = cv2.cvtColor(previous_frame, cv2.COLOR_RGB2GRAY)
            
            # Calculate absolute difference between frames
            diff = cv2.absdiff(current_gray, previous_gray)
            
            # Apply threshold to get binary difference image
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            
            # Apply morphological operations to clean up noise
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            
            # Calculate percentage of changed pixels
            total_pixels = thresh.shape[0] * thresh.shape[1]
            changed_pixels = cv2.countNonZero(thresh)
            change_percentage = (changed_pixels / total_pixels) * 100
            
            logger.debug(f"Frame difference: {change_percentage:.2f}% changed pixels")
            
            # Check if change exceeds threshold (turtle moved significantly)
            if change_percentage > config.camera.frame_comparison_threshold:
                # Find contours in the difference image
                contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                # Filter contours by area (turtle-sized movements)
                valid_contours = [c for c in contours if cv2.contourArea(c) > config.motion.min_blob_area]
                
                if valid_contours:
                    # Get the largest contour (main turtle movement)
                    largest_contour = max(valid_contours, key=cv2.contourArea)
                    x, y, w, h = cv2.boundingRect(largest_contour)
                    logger.info(f"Turtle motion detected: {change_percentage:.2f}% change, bbox: ({x},{y},{w},{h})")
                    return True, (x, y, w, h)
            
            return False, None
            
        except Exception as e:
            logger.error(f"Still frame comparison error: {e}")
            return False, None
    
    def _create_high_res_crop(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
        """Create high-resolution crop from 4K motion frame"""
        try:
            x, y, w, h = bbox
            
            # Add margin around the detection
            margin_x = int(w * config.camera.crop_margin_percent / 100)
            margin_y = int(h * config.camera.crop_margin_percent / 100)
            
            # Calculate crop boundaries
            crop_x = max(0, x - margin_x)
            crop_y = max(0, y - margin_y)
            crop_w = min(config.camera.motion_width - crop_x, w + 2 * margin_x)
            crop_h = min(config.camera.motion_height - crop_y, h + 2 * margin_y)
            
            # Extract high-resolution crop
            crop = frame[crop_y:crop_y+crop_h, crop_x:crop_x+crop_w]
            
            # Optionally downscale for Telegram (to keep file sizes reasonable)
            if crop.shape[1] > config.camera.alert_downscale_width:
                scale_factor = config.camera.alert_downscale_width / crop.shape[1]
                new_width = int(crop.shape[1] * scale_factor)
                new_height = int(crop.shape[0] * scale_factor)
                crop = cv2.resize(crop, (new_width, new_height), interpolation=cv2.INTER_AREA)
            
            return crop
            
        except Exception as e:
            logger.error(f"Failed to create high-res crop: {e}")
            return None
    
    def _save_frame_data(self, motion_frame: MotionFrame):
        """Save frame data to disk and database"""
        try:
            timestamp_str = motion_frame.timestamp.strftime("%Y%m%d_%H%M%S_%f")[:-3]
            date_str = motion_frame.timestamp.strftime("%Y-%m-%d")
            
            # Create date directory
            frames_dir = config.get_frames_path() / date_str
            frames_dir.mkdir(parents=True, exist_ok=True)
            
            # Save high-resolution crop as JPEG
            if motion_frame.high_res_crop is not None:
                crop_filename = f"{timestamp_str}_crop.jpg"
                crop_path = frames_dir / crop_filename
                
                # Convert to BGR for saving
                crop_bgr = cv2.cvtColor(motion_frame.high_res_crop, cv2.COLOR_RGB2BGR)
                cv2.imwrite(str(crop_path), crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, config.alert.quality])
            else:
                logger.warning("No high-res crop available, skipping frame save")
                return
                
                # Save metadata as JSON
                metadata = {
                    "timestamp": motion_frame.timestamp.isoformat(),
                    "bbox": motion_frame.bbox,
                    "confidence": motion_frame.confidence,
                    "crop_path": str(crop_path)
                }
                
                metadata_path = frames_dir / f"{timestamp_str}_meta.json"
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
                
                # Save to database
                if motion_frame.bbox:
                    detection = Detection(
                        timestamp=motion_frame.timestamp,
                        bbox_x=motion_frame.bbox[0],
                        bbox_y=motion_frame.bbox[1],
                        bbox_w=motion_frame.bbox[2],
                        bbox_h=motion_frame.bbox[3],
                        confidence=motion_frame.confidence,
                        img_path=str(crop_path)
                    )
                    db.insert_detection(detection)
                
                # Save ML training frame if enabled
                if config.storage.save_ml_frames and config.get_ml_frames_path():
                    ml_dir = config.get_ml_frames_path() / date_str
                    ml_dir.mkdir(parents=True, exist_ok=True)
                    ml_crop_path = ml_dir / crop_filename
                    cv2.imwrite(str(ml_crop_path), crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
                
                logger.debug(f"Saved frame data: {crop_filename}")
                
        except Exception as e:
            logger.error(f"Failed to save frame data: {e}")
    
    def _trigger_telegram_alert(self):
        """Trigger Telegram alert by calling the bot service"""
        try:
            import subprocess
            # Call the telegram bot to send an alert
            result = subprocess.run([
                "/opt/turtlecam/venv/bin/python3", 
                "/opt/turtlecam/telegram_bot.py", 
                "--alert"
            ], capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                logger.info("Telegram alert triggered successfully")
            else:
                logger.error(f"Failed to trigger Telegram alert: {result.stderr}")
        except Exception as e:
            logger.error(f"Failed to trigger Telegram alert: {e}")
    
    def _process_motion_event(self):
        """Process accumulated motion frames into alert"""
        if not self.current_event_frames:
            return
        
        logger.info(f"Processing motion event with {len(self.current_event_frames)} frames")
        
        # Save all frames from the event
        for frame in self.current_event_frames:
            self._save_frame_data(frame)
        
        # Trigger GIF/video creation (handled by separate service)
        self.motion_event.set()
        
        # Trigger Telegram alert directly
        self._trigger_telegram_alert()
        
        # Clear event frames
        self.current_event_frames.clear()
    
    def start(self):
        """Start motion detection"""
        if self.running:
            return
        
        self.running = True
        logger.info("Starting motion detection")
        
        try:
            self.camera.start()
            
            while self.running:
                current_time = time.time()
                timestamp = datetime.now()
                
                # Check if it's time to capture a new still frame
                if current_time - self.last_capture_time < config.camera.still_frame_interval:
                    time.sleep(0.1)  # Small sleep to prevent CPU spinning
                    continue
                
                # Capture still frame (memory efficient single capture)
                frame = self.camera.capture_array("main")
                self.last_capture_time = current_time
                
                logger.debug(f"Captured still frame at {timestamp}")
                
                # Check for frame corruption
                if self._is_frame_corrupted(frame):
                    logger.warning("Corrupted frame detected, skipping")
                    continue
                
                # Compare with previous frame if we have one
                has_motion = False
                bbox = None
                
                if self.previous_frame is not None:
                    has_motion, bbox = self._compare_still_frames(frame, self.previous_frame)
                else:
                    logger.info("First frame captured, storing as reference")
                
                # Store current frame as previous for next comparison
                self.previous_frame = frame.copy()
                
                if has_motion:
                    logger.debug(f"Motion detected: {bbox}")
                    self.last_motion_time = current_time
                    
                    # Start new event if needed
                    if not self.current_event_frames:
                        self.event_start_time = current_time
                        logger.info("Motion event started")
                    
                    # Create high-resolution crop from 4K frame
                    high_res_crop = self._create_high_res_crop(frame, bbox)
                    
                    # Create motion frame
                    motion_frame = MotionFrame(
                        timestamp=timestamp,
                        motion_frame=frame.copy(),
                        bbox=bbox,
                        high_res_crop=high_res_crop
                    )
                    
                    # Add to current event
                    self.current_event_frames.append(motion_frame)
                    
                    # Limit event length
                    if len(self.current_event_frames) > config.alert.max_frames:
                        self.current_event_frames.pop(0)
                
                else:
                    # Check for event timeout
                    if (self.current_event_frames and 
                        current_time - self.last_motion_time > config.motion.inactivity_timeout):
                        
                        logger.info("Motion event ended (timeout)")
                        self._process_motion_event()
                
                # Control frame rate
                time.sleep(1.0 / config.camera.motion_fps)
                
        except Exception as e:
            logger.error(f"Motion detection error: {e}")
        finally:
            if self.camera:
                self.camera.stop()
            logger.info("Motion detection stopped")
    
    def stop(self):
        """Stop motion detection"""
        self.running = False
        
        # Process any remaining event
        if self.current_event_frames:
            self._process_motion_event()
    
    def get_recent_frames(self, count: int = 10) -> List[MotionFrame]:
        """Get recent motion frames for manual GIF creation"""
        frames = []
        temp_frames = []
        
        # Drain queue into temporary list
        try:
            while not self.motion_frames.empty():
                temp_frames.append(self.motion_frames.get_nowait())
        except Empty:
            pass
        
        # Get the most recent frames
        frames = temp_frames[-count:] if len(temp_frames) >= count else temp_frames
        
        # Put frames back in queue
        for frame in temp_frames:
            try:
                self.motion_frames.put_nowait(frame)
            except:
                break  # Queue full
        
        return frames


def main():
    """Main entry point for motion detection service"""
    import sys
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, config.system.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('/var/log/turtle/motion.log')
        ]
    )
    
    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error(f"Configuration errors: {errors}")
        sys.exit(1)
    
    # Create motion detector and start
    detector = MotionDetector()
    
    try:
        detector.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
    finally:
        detector.stop()


if __name__ == "__main__":
    main()
