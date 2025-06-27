"""Motion detector module for TurtleCam.

This module uses background subtraction to detect motion in camera frames.
When significant motion is detected, it triggers frame capture for further processing.
"""

import cv2
import numpy as np
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MotionDetector:
    """Motion detector using background subtraction.
    
    Detects motion in video frames using OpenCV's background subtraction algorithms.
    """
    
    def __init__(self, 
                 min_area=800,
                 history=500,
                 var_threshold=16,
                 detect_shadows=True):
        """Initialize the motion detector.
        
        Args:
            min_area (int): Minimum contour area to be considered motion (px²)
            history (int): Length of history for background subtractor
            var_threshold (float): Threshold for background/foreground decision
            detect_shadows (bool): Whether to detect and mark shadows
        """
        self.min_area = min_area
        # Initialize background subtractor (MOG2)
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=history,
            varThreshold=var_threshold,
            detectShadows=detect_shadows
        )
        
        # Initialize state variables
        self.last_detection_time = None
        self.detection_count = 0
    
    def detect(self, frame):
        """Detect motion in a frame.
        
        Args:
            frame (numpy.ndarray): Input frame (should be grayscale)
            
        Returns:
            tuple: (motion_detected, bounding_box, mask)
                motion_detected (bool): True if motion detected
                bounding_box (tuple): (x, y, w, h) of motion area or None
                mask (numpy.ndarray): Foreground mask
        """
        # Apply background subtraction
        fg_mask = self.bg_subtractor.apply(frame)
        
        # Apply morphological operations to remove noise
        kernel = np.ones((3, 3), np.uint8)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, kernel)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_CLOSE, kernel)
        
        # Find contours in the mask
        contours, _ = cv2.findContours(
            fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        
        # Initialize variables
        motion_detected = False
        bounding_box = None
        
        # Find the largest contour
        if contours:
            largest_contour = max(contours, key=cv2.contourArea)
            area = cv2.contourArea(largest_contour)
            
            # If the contour area exceeds our threshold, we have motion
            if area >= self.min_area:
                x, y, w, h = cv2.boundingRect(largest_contour)
                bounding_box = (x, y, w, h)
                motion_detected = True
                
                # Update state
                self.last_detection_time = datetime.now()
                self.detection_count += 1
                
                logger.debug(f"Motion detected: Area={area}px², BBox={bounding_box}")
        
        return motion_detected, bounding_box, fg_mask
    
    def get_time_since_last_detection(self):
        """Get time elapsed since the last motion detection.
        
        Returns:
            float: Time in seconds since last detection, or None if no detection yet
        """
        if self.last_detection_time is None:
            return None
        
        elapsed = (datetime.now() - self.last_detection_time).total_seconds()
        return elapsed
    
    def reset(self):
        """Reset the motion detector state."""
        self.last_detection_time = None
        self.detection_count = 0
