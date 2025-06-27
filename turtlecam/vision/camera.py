"""Camera interface for TurtleCam.

This module provides a wrapper around picamera2 for capturing preview frames and
high-resolution crops using the Arducam 64MP camera.
"""

import time
import logging
import threading
from pathlib import Path
import numpy as np

# Import picamera2 with a try-except to allow for development on non-Pi systems
try:
    from picamera2 import Picamera2
    from picamera2.encoders import JpegEncoder
    from picamera2.outputs import FileOutput
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False
    logging.warning("picamera2 not available, using mock camera")

logger = logging.getLogger(__name__)


class Camera:
    """Camera interface for the Arducam 64MP.
    
    Handles preview stream capture and high-resolution cropping.
    """
    
    def __init__(self, 
                 preview_size=(640, 480),
                 crop_size=(1920, 1920),
                 fps=8,
                 mock_mode=not PICAMERA_AVAILABLE):
        """Initialize camera interface.
        
        Args:
            preview_size (tuple): Width, height of preview stream
            crop_size (tuple): Maximum width, height for high-res crops
            fps (int): Target frame rate for preview stream
            mock_mode (bool): If True, use a mock camera for testing
        """
        self.preview_size = preview_size
        self.crop_size = crop_size
        self.fps = fps
        self.mock_mode = mock_mode
        self.lock = threading.RLock()
        
        # Camera state
        self.camera = None
        self.running = False
        self.current_frame = None
        self.frame_count = 0
        
        # Initialize the camera (real or mock)
        self._initialize_camera()
        
    def _initialize_camera(self):
        """Initialize the camera hardware or mock."""
        if self.mock_mode:
            logger.info("Initializing mock camera")
            # In mock mode, we'll generate simple test frames
            return
        
        logger.info("Initializing Picamera2")
        self.camera = Picamera2()
        
        # Configure preview stream
        preview_config = self.camera.create_preview_configuration(
            main={"size": self.preview_size, "format": "RGB888"},
            lores={"size": (320, 240), "format": "YUV420"}
        )
        self.camera.configure(preview_config)
    
    def start(self):
        """Start the camera and begin capturing frames."""
        with self.lock:
            if self.running:
                logger.warning("Camera already running")
                return
            
            self.running = True
            
            if self.mock_mode:
                # Start a thread for mock camera
                self.mock_thread = threading.Thread(target=self._mock_capture_loop)
                self.mock_thread.daemon = True
                self.mock_thread.start()
                logger.info("Started mock camera thread")
            else:
                # Start the real camera
                self.camera.start()
                logger.info("Started Picamera2")
    
    def stop(self):
        """Stop the camera."""
        with self.lock:
            if not self.running:
                return
                
            self.running = False
            
            if not self.mock_mode and self.camera:
                self.camera.stop()
                logger.info("Stopped Picamera2")
    
    def get_frame(self):
        """Get the latest preview frame.
        
        Returns:
            numpy.ndarray: RGB frame at preview resolution or None if not available
        """
        with self.lock:
            if self.mock_mode:
                return self.current_frame
            
            if not self.running or not self.camera:
                return None
                
            try:
                frame = self.camera.capture_array()
                self.current_frame = frame
                self.frame_count += 1
                return frame
            except Exception as e:
                logger.error(f"Error capturing frame: {e}")
                return None
    
    def capture_high_res_crop(self, bbox, output_path):
        """Capture a high-resolution crop using the 64MP full sensor.
        
        Args:
            bbox (tuple): Bounding box (x, y, w, h) in preview coordinates
            output_path (str or Path): Path to save the JPEG image
        
        Returns:
            bool: True if capture was successful
        """
        if self.mock_mode:
            # In mock mode, just save the current frame
            self._save_mock_crop(bbox, output_path)
            return True
        
        if not self.running or not self.camera:
            logger.error("Camera not running, can't capture high-res crop")
            return False
            
        try:
            # Scale bbox to full sensor coordinates (this would need calibration in practice)
            # For now, we'll use simple scaling based on resolution difference
            scale_x = 9152 / self.preview_size[0]  # 9152 is the full 64MP width
            scale_y = 6944 / self.preview_size[1]  # 6944 is the full 64MP height
            
            x, y, w, h = bbox
            # Scale and ensure we don't exceed sensor bounds
            x_scaled = int(x * scale_x)
            y_scaled = int(y * scale_y)
            w_scaled = min(int(w * scale_x), self.crop_size[0])
            h_scaled = min(int(h * scale_y), self.crop_size[1])
            
            # Ensure we stay within sensor bounds
            x_scaled = max(0, min(x_scaled, 9152 - w_scaled))
            y_scaled = max(0, min(y_scaled, 6944 - h_scaled))
            
            # Create a new configuration for the capture with ScalerCrop
            still_config = self.camera.create_still_configuration(
                main={"size": (w_scaled, h_scaled), "format": "RGB888"},
                transform={"crop": (x_scaled, y_scaled, w_scaled, h_scaled)}
            )
            
            # Capture the image
            self.camera.switch_mode_and_capture_file(
                still_config,
                output_path,
                format="jpg",
                wait=True
            )
            
            logger.info(f"Captured high-res crop to {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error capturing high-res crop: {e}")
            return False
    
    def _mock_capture_loop(self):
        """Generate mock frames for testing."""
        try:
            # Create a simple color gradient as our mock frame
            y, x = np.mgrid[:self.preview_size[1], :self.preview_size[0]]
            
            while self.running:
                # Create a rolling color pattern that changes over time
                t = time.time() % 10  # 10-second cycle
                r = (np.sin(x * 0.01 + t) + 1) * 127
                g = (np.sin(y * 0.01 + t * 2) + 1) * 127
                b = (np.sin((x + y) * 0.01 + t * 3) + 1) * 127
                
                # Combine channels
                frame = np.zeros((self.preview_size[1], self.preview_size[0], 3), dtype=np.uint8)
                frame[..., 0] = r.astype(np.uint8)
                frame[..., 1] = g.astype(np.uint8)
                frame[..., 2] = b.astype(np.uint8)
                
                # Add a moving "turtle" (just a dark blob)
                center_x = int((np.sin(t * 0.5) + 1) * self.preview_size[0] / 2)
                center_y = int((np.cos(t * 0.3) + 1) * self.preview_size[1] / 2)
                radius = 30
                y_grid, x_grid = np.ogrid[-center_y:self.preview_size[1]-center_y, -center_x:self.preview_size[0]-center_x]
                mask = x_grid*x_grid + y_grid*y_grid <= radius*radius
                frame[mask] = 30  # Dark blob
                
                # Update current frame
                with self.lock:
                    self.current_frame = frame
                    self.frame_count += 1
                
                # Sleep to maintain target frame rate
                time.sleep(1.0 / self.fps)
                
        except Exception as e:
            logger.error(f"Error in mock capture loop: {e}")
        finally:
            logger.info("Mock capture loop ended")
            
    def _save_mock_crop(self, bbox, output_path):
        """Save a cropped portion of the mock frame."""
        import cv2
        
        with self.lock:
            if self.current_frame is None:
                return False
            
            x, y, w, h = bbox
            # Ensure bounds
            x = max(0, x)
            y = max(0, y)
            w = min(w, self.preview_size[0] - x)
            h = min(h, self.preview_size[1] - y)
            
            # Crop and save
            crop = self.current_frame[y:y+h, x:x+w]
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            cv2.imwrite(str(output_path), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
            logger.info(f"Saved mock crop to {output_path}")
            return True
