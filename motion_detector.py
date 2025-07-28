"""
TurtleCam Motion Detection
Background subtraction-based motion detection optimized for Hermann's tortoise behavior.
"""

import cv2
import numpy as np
import logging
import time
import gc
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, List
from threading import Thread, Event
from queue import Queue, Empty
import json

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


class TurtleTracker:
    """Stable turtle tracking for consistent GIF crops"""
    
    def __init__(self):
        self.last_bbox = None
        self.tracking_confidence = 0
        self.template = None
        
    def track_turtle(self, current_frame, previous_frame):
        """Stable turtle tracking for consistent GIF crops"""
        
        if self.last_bbox is None:
            # Initial detection
            has_motion, bbox = self._turtle_localization_comparison(previous_frame, current_frame)
            if has_motion:
                self.last_bbox = bbox
                self.tracking_confidence = 1.0
                logger.info(f"Initial turtle detection: bbox {bbox}")
            return has_motion, bbox
        
        # Try template matching first (most stable)
        has_motion, bbox = self._template_tracking_comparison(
            previous_frame, current_frame, self.last_bbox)
        
        if has_motion and bbox:
            # Smooth the bounding box (prevent jittery crops)
            smooth_bbox = self._smooth_bbox(bbox, self.last_bbox)
            self.last_bbox = smooth_bbox
            self.tracking_confidence = min(1.0, self.tracking_confidence + 0.1)
            logger.debug(f"Template tracking: bbox {smooth_bbox}, confidence {self.tracking_confidence:.2f}")
            return True, smooth_bbox
        
        # Fallback to contour detection
        self.tracking_confidence *= 0.8
        if self.tracking_confidence < 0.3:
            logger.info("Tracking confidence low, resetting tracker")
            self.last_bbox = None  # Reset tracking
            
        return False, self.last_bbox
    
    def _turtle_localization_comparison(self, frame1, frame2):
        """Optimized for turtle localization and stable crops"""
        try:
            # Stage 1: Fast motion detection on tiny frame
            tiny1 = cv2.resize(frame1, (80, 60), interpolation=cv2.INTER_NEAREST)
            tiny2 = cv2.resize(frame2, (80, 60), interpolation=cv2.INTER_NEAREST)
            
            diff_tiny = cv2.absdiff(tiny1, tiny2)
            if np.mean(diff_tiny) < 10:  # No motion
                return False, None
            
            # Stage 2: Localization on medium frame (for accurate bbox)
            med1 = cv2.resize(frame1, (320, 240), interpolation=cv2.INTER_AREA)
            med2 = cv2.resize(frame2, (320, 240), interpolation=cv2.INTER_AREA)
            
            # Convert to grayscale for contour detection
            gray1 = cv2.cvtColor(med1, cv2.COLOR_RGB2GRAY)
            gray2 = cv2.cvtColor(med2, cv2.COLOR_RGB2GRAY)
            
            # Find difference and contours
            diff = cv2.absdiff(gray1, gray2)
            _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            
            # Clean up with morphology
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            
            # Find contours
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            # Filter for turtle-sized objects
            turtle_contours = [c for c in contours if 200 < cv2.contourArea(c) < 5000]
            
            if turtle_contours:
                # Get largest turtle-like contour
                largest = max(turtle_contours, key=cv2.contourArea)
                x, y, w, h = cv2.boundingRect(largest)
                
                # Scale back to full resolution
                scale_x = frame1.shape[1] / 320
                scale_y = frame1.shape[0] / 240
                
                full_x = int(x * scale_x)
                full_y = int(y * scale_y)
                full_w = int(w * scale_x)
                full_h = int(h * scale_y)
                
                return True, (full_x, full_y, full_w, full_h)
            
            return False, None
            
        except Exception as e:
            logger.error(f"Turtle localization failed: {e}")
            return False, None
    
    def _template_tracking_comparison(self, frame1, frame2, previous_bbox):
        """Track turtle using template matching for stable crops"""
        try:
            if previous_bbox is None:
                return self._turtle_localization_comparison(frame1, frame2)
            
            # Extract turtle template from previous frame
            x, y, w, h = previous_bbox
            margin = 20
            
            # Ensure template bounds are valid
            y1 = max(0, y - margin)
            y2 = min(frame1.shape[0], y + h + margin)
            x1 = max(0, x - margin)
            x2 = min(frame1.shape[1], x + w + margin)
            
            template = frame1[y1:y2, x1:x2]
            
            if template.size == 0 or template.shape[0] < 10 or template.shape[1] < 10:
                return self._turtle_localization_comparison(frame1, frame2)
            
            # Search for turtle in current frame (expanded search area)
            search_margin = 100
            search_x1 = max(0, x - search_margin)
            search_y1 = max(0, y - search_margin)
            search_x2 = min(frame2.shape[1], x + w + search_margin)
            search_y2 = min(frame2.shape[0], y + h + search_margin)
            
            search_area = frame2[search_y1:search_y2, search_x1:search_x2]
            
            if search_area.size == 0:
                return self._turtle_localization_comparison(frame1, frame2)
            
            # Template matching
            result = cv2.matchTemplate(search_area, template, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            
            if max_val > 0.6:  # Good match found
                # Convert back to full frame coordinates
                new_x = search_x1 + max_loc[0]
                new_y = search_y1 + max_loc[1]
                
                return True, (new_x, new_y, w, h)
            
            # Fallback to contour detection
            return self._turtle_localization_comparison(frame1, frame2)
            
        except Exception as e:
            logger.error(f"Template tracking failed: {e}")
            return self._turtle_localization_comparison(frame1, frame2)
    
    def _smooth_bbox(self, new_bbox, old_bbox, alpha=0.7):
        """Smooth bounding box transitions for stable crops"""
        if old_bbox is None:
            return new_bbox
            
        # Weighted average for smooth transitions
        x = int(alpha * new_bbox[0] + (1-alpha) * old_bbox[0])
        y = int(alpha * new_bbox[1] + (1-alpha) * old_bbox[1])
        w = int(alpha * new_bbox[2] + (1-alpha) * old_bbox[2])
        h = int(alpha * new_bbox[3] + (1-alpha) * old_bbox[3])
        
        return (x, y, w, h)


class MotionDetector:
    """Motion detection with hybrid turtle tracking for stable GIF crops"""
    
    def __init__(self):
        self.camera = None
        self.previous_frame = None  # Store previous still frame for comparison
        self.motion_frames = []
        self.last_motion_time = 0
        self.motion_event_active = False
        self.last_capture_time = 0
        self.running = False  # Control flag for main loop
        self.current_event_frames = []  # Store frames during motion events
        self.motion_event = Event()  # Threading event for motion detection
        self.turtle_tracker = TurtleTracker()  # Hybrid tracking system
        # Initialize camera for still frame capture
        self._setup_camera()
    
    def _setup_camera(self):
        """Initialize Picamera2 with preview and full-res configurations"""
        try:
            self.camera = Picamera2()
            
            # Configure high-resolution capture with memory optimization
            motion_config = self.camera.create_preview_configuration(
                main={
                    "size": (config.camera.capture_width, config.camera.capture_height),
                    "format": "RGB888"
                },
                buffer_count=2  # Minimize buffer count to reduce memory usage
            )
            
            self.camera.configure(motion_config)
            
            # Set manual controls to avoid auto-adjustments causing false motion
            try:
                self.camera.set_controls({
                    "LensPosition": 3.0,      # Manual focus
                    "AeEnable": False,        # Disable auto-exposure
                    "AwbEnable": False,       # Disable auto-white-balance
                    "ExposureTime": 10000,    # Fixed exposure (10ms)
                    "AnalogueGain": 2.0,      # Fixed gain
                })
                logger.info("Manual controls set (focus, exposure, white balance fixed)")
            except Exception as e:
                logger.warning(f"Could not set manual controls: {e}")
            
            logger.info(f"Camera configured: Dual-resolution system - Capture: {config.camera.capture_width}x{config.camera.capture_height}, Comparison: {config.camera.comparison_width}x{config.camera.comparison_height} @ {config.camera.motion_fps}fps")
            
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
        """Compare two still frames using low-res comparison for speed"""
        try:
            # Ultra-fast resize to tiny frames (4.6K -> 320x240 = 200x faster!)
            comparison_size = (config.camera.comparison_width, config.camera.comparison_height)
            
            # Use fastest interpolation for speed
            current_small = cv2.resize(current_frame, comparison_size, interpolation=cv2.INTER_NEAREST)
            previous_small = cv2.resize(previous_frame, comparison_size, interpolation=cv2.INTER_NEAREST)
            
            # Convert tiny frames to grayscale (much faster on 320x240)
            current_gray = cv2.cvtColor(current_small, cv2.COLOR_RGB2GRAY)
            previous_gray = cv2.cvtColor(previous_small, cv2.COLOR_RGB2GRAY)
            
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
                    x_small, y_small, w_small, h_small = cv2.boundingRect(largest_contour)
                    
                    # Scale bounding box back to high-res coordinates
                    scale_x = config.camera.capture_width / config.camera.comparison_width
                    scale_y = config.camera.capture_height / config.camera.comparison_height
                    
                    x = int(x_small * scale_x)
                    y = int(y_small * scale_y)
                    w = int(w_small * scale_x)
                    h = int(h_small * scale_y)
                    
                    logger.info(f"Turtle motion detected: {change_percentage:.2f}% change, bbox: ({x},{y},{w},{h}) [scaled from low-res]")
                    return True, (x, y, w, h)
            
            return False, None
            
        except Exception as e:
            logger.error(f"Still frame comparison error: {e}")
            return False, None
    
    def _crop_motion_area(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        """Crop the motion area from the frame with margin using tracking bbox"""
        try:
            x, y, w, h = bbox
            
            # Add margin around the detected turtle
            margin = config.motion.crop_margin
            
            # Calculate crop bounds with margin
            crop_x1 = max(0, x - margin)
            crop_y1 = max(0, y - margin)
            crop_x2 = min(frame.shape[1], x + w + margin)
            crop_y2 = min(frame.shape[0], y + h + margin)
            
            # Ensure minimum crop size for turtle visibility
            min_crop_size = 200
            crop_w = crop_x2 - crop_x1
            crop_h = crop_y2 - crop_y1
            
            if crop_w < min_crop_size or crop_h < min_crop_size:
                # Expand crop to minimum size, centered on turtle
                center_x = x + w // 2
                center_y = y + h // 2
                
                half_size = max(min_crop_size // 2, max(crop_w, crop_h) // 2)
                
                crop_x1 = max(0, center_x - half_size)
                crop_y1 = max(0, center_y - half_size)
                crop_x2 = min(frame.shape[1], center_x + half_size)
                crop_y2 = min(frame.shape[0], center_y + half_size)
            
            # Crop the frame
            cropped = frame[crop_y1:crop_y2, crop_x1:crop_x2]
            
            logger.debug(f"Cropped turtle area: {cropped.shape} from tracking bbox {bbox}")
            return cropped
            
        except Exception as e:
            logger.error(f"Failed to crop turtle area: {e}")
            # Return center crop as fallback
            h, w = frame.shape[:2]
            center_x, center_y = w // 2, h // 2
            crop_size = min(w, h) // 2
            return frame[center_y-crop_size//2:center_y+crop_size//2,
                       center_x-crop_size//2:center_x+crop_size//2]
    
    def _create_high_res_crop(self, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
        """Create high-resolution crop from 4K motion frame"""
        try:
            cropped = self._crop_motion_area(frame, bbox)
            
            # Optionally downscale for Telegram (to keep file sizes reasonable)
            if cropped.shape[1] > config.camera.alert_downscale_width:
                scale_factor = config.camera.alert_downscale_width / cropped.shape[1]
                new_width = int(cropped.shape[1] * scale_factor)
                new_height = int(cropped.shape[0] * scale_factor)
                cropped = cv2.resize(cropped, (new_width, new_height), interpolation=cv2.INTER_AREA)
            
            return cropped
            
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
            
            # Let camera stabilize (auto-exposure/white-balance settle)
            logger.info("Camera stabilizing for 3 seconds...")
            time.sleep(3)
            
            while self.running:
                current_time = time.time()
                timestamp = datetime.now()
                
                # Check if it's time to capture a new still frame (timelapse mode)
                time_since_last = current_time - self.last_capture_time
                if time_since_last < config.camera.still_frame_interval:
                    remaining = config.camera.still_frame_interval - time_since_last
                    if remaining > 1.0:  # Only log if more than 1 second remaining
                        logger.debug(f"Timelapse waiting: {remaining:.1f}s until next frame")
                    time.sleep(1.0)  # Sleep 1 second at a time for responsive logging
                    continue
                
                # Capture still frame (memory efficient single capture)
                frame = self.camera.capture_array("main")
                self.last_capture_time = current_time
                
                logger.debug(f"Captured still frame at {timestamp}")
                
                # Check for frame corruption
                if self._is_frame_corrupted(frame):
                    logger.warning("Corrupted frame detected, skipping")
                    continue
                
                # Hybrid turtle tracking for stable GIF crops
                has_motion = False
                bbox = None
                
                if self.previous_frame is not None:
                    logger.debug("Tracking turtle for motion detection...")
                    try:
                        # Use hybrid tracking system for stable localization
                        has_motion, bbox = self.turtle_tracker.track_turtle(frame, self.previous_frame)
                        
                        if has_motion and bbox:
                            logger.info(f"Turtle motion detected! Bbox: {bbox}")
                        else:
                            logger.debug("No turtle motion detected")
                            
                    except Exception as e:
                        logger.error(f"Turtle tracking failed: {e}")
                else:
                    logger.info("First frame captured, storing as reference")
                
                # Store current frame (avoid expensive copy - just keep reference)
                logger.debug("Storing frame reference...")
                self.previous_frame = frame  # Just reference, no copy!
                
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
