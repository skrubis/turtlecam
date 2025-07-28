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
    
    def __init__(self, timestamp: datetime, preview_frame: np.ndarray, 
                 bbox: Optional[Tuple[int, int, int, int]] = None,
                 full_res_crop: Optional[np.ndarray] = None):
        self.timestamp = timestamp
        self.preview_frame = preview_frame
        self.bbox = bbox  # (x, y, w, h) in preview coordinates
        self.full_res_crop = full_res_crop
        self.confidence = 1.0


class MotionDetector:
    """Motion detection using background subtraction with morphological filtering"""
    
    def __init__(self):
        self.camera = None
        self.background_subtractor = None
        self.running = False
        self.motion_event = Event()
        
        # Frame buffers
        self.motion_frames = Queue(maxsize=config.alert.max_frames * 2)
        self.current_event_frames = []
        
        # Timing
        self.last_motion_time = 0
        self.event_start_time = 0
        
        # Initialize camera
        self._setup_camera()
        self._setup_background_subtractor()
    
    def _setup_camera(self):
        """Initialize Picamera2 with preview and full-res configurations"""
        try:
            self.camera = Picamera2()
            
            # Configure preview stream for motion detection
            preview_config = self.camera.create_preview_configuration(
                main={
                    "size": (config.camera.preview_width, config.camera.preview_height),
                    "format": "RGB888"
                }
            )
            
            # Configure full-res stream for high-quality crops
            full_res_config = self.camera.create_still_configuration(
                main={
                    "size": (config.camera.full_res_width, config.camera.full_res_height),
                    "format": "RGB888"
                }
            )
            
            self.camera.configure(preview_config)
            logger.info(f"Camera configured: preview {config.camera.preview_width}x{config.camera.preview_height}")
            
        except Exception as e:
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
    
    def _preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """Preprocess frame for motion detection"""
        # Convert to grayscale for background subtraction
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        
        # Apply Gaussian blur to reduce noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        return blurred
    
    def _detect_motion(self, frame: np.ndarray) -> Tuple[bool, Optional[Tuple[int, int, int, int]]]:
        """Detect motion and return bounding box if found"""
        processed_frame = self._preprocess_frame(frame)
        
        # Apply background subtraction
        fg_mask = self.background_subtractor.apply(processed_frame)
        
        # Morphological operations to reduce noise
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, 
            (config.motion.morphology_kernel_size, config.motion.morphology_kernel_size)
        )
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
        
        # Find contours
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Filter contours by area
        valid_contours = [c for c in contours if cv2.contourArea(c) > config.motion.min_blob_area]
        
        if not valid_contours:
            return False, None
        
        # Find the largest contour (most likely the turtle)
        largest_contour = max(valid_contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest_contour)
        
        return True, (x, y, w, h)
    
    def _capture_full_res_crop(self, bbox: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
        """Capture high-resolution crop around detected motion"""
        try:
            x, y, w, h = bbox
            
            # Scale bounding box from preview to full resolution
            scale_x = config.camera.full_res_width / config.camera.preview_width
            scale_y = config.camera.full_res_height / config.camera.preview_height
            
            # Apply margin and scale
            margin_x = int(w * config.camera.crop_margin_percent / 100)
            margin_y = int(h * config.camera.crop_margin_percent / 100)
            
            crop_x = max(0, int((x - margin_x) * scale_x))
            crop_y = max(0, int((y - margin_y) * scale_y))
            crop_w = min(config.camera.full_res_width - crop_x, int((w + 2 * margin_x) * scale_x))
            crop_h = min(config.camera.full_res_height - crop_y, int((h + 2 * margin_y) * scale_y))
            
            # Capture full resolution image
            full_res_array = self.camera.capture_array("main")
            
            # Extract crop
            crop = full_res_array[crop_y:crop_y+crop_h, crop_x:crop_x+crop_w]
            
            return crop
            
        except Exception as e:
            logger.error(f"Failed to capture full-res crop: {e}")
            return None
    
    def _save_frame_data(self, motion_frame: MotionFrame):
        """Save frame data to disk and database"""
        try:
            timestamp_str = motion_frame.timestamp.strftime("%Y%m%d_%H%M%S_%f")[:-3]
            date_str = motion_frame.timestamp.strftime("%Y-%m-%d")
            
            # Create date directory
            frames_dir = config.get_frames_path() / date_str
            frames_dir.mkdir(parents=True, exist_ok=True)
            
            # Save high-res crop as JPEG
            if motion_frame.full_res_crop is not None:
                crop_filename = f"{timestamp_str}_crop.jpg"
                crop_path = frames_dir / crop_filename
                
                # Convert to BGR for saving (check if frame is not empty)
                if motion_frame.full_res_crop is None or motion_frame.full_res_crop.size == 0:
                    logger.warning("Full-res crop is empty, using preview frame instead")
                    # Fallback to preview frame if full-res crop failed
                    if motion_frame.frame is not None and motion_frame.frame.size > 0:
                        crop_bgr = cv2.cvtColor(motion_frame.frame, cv2.COLOR_RGB2BGR)
                    else:
                        logger.warning("Both full-res and preview frames are empty, skipping")
                        return
                else:
                    crop_bgr = cv2.cvtColor(motion_frame.full_res_crop, cv2.COLOR_RGB2BGR)
                cv2.imwrite(str(crop_path), crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, config.alert.quality])
                
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
                # Capture preview frame
                frame = self.camera.capture_array("main")
                current_time = time.time()
                timestamp = datetime.now()
                
                # Detect motion
                has_motion, bbox = self._detect_motion(frame)
                
                if has_motion:
                    logger.debug(f"Motion detected: {bbox}")
                    self.last_motion_time = current_time
                    
                    # Start new event if needed
                    if not self.current_event_frames:
                        self.event_start_time = current_time
                        logger.info("Motion event started")
                    
                    # Capture high-res crop
                    full_res_crop = self._capture_full_res_crop(bbox)
                    
                    # Create motion frame
                    motion_frame = MotionFrame(
                        timestamp=timestamp,
                        preview_frame=frame.copy(),
                        bbox=bbox,
                        full_res_crop=full_res_crop
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
                time.sleep(1.0 / config.camera.preview_fps)
                
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
