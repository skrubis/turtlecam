"""
TurtleCam GIF/Video Builder
Creates motion alerts from captured frames with configurable output format.
"""

import cv2
import numpy as np
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
import json
import tempfile
import subprocess

from PIL import Image, ImageSequence
from config import config

logger = logging.getLogger(__name__)


class AlertBuilder:
    """Builds GIF or MP4 alerts from motion frames"""
    
    def __init__(self):
        self.temp_dir = Path(tempfile.gettempdir()) / "turtlecam"
        self.temp_dir.mkdir(exist_ok=True)
    
    def _load_frames_from_event(self, event_dir: Path) -> List[Tuple[datetime, np.ndarray, dict]]:
        """Load frames from a motion event directory"""
        frames = []
        
        # Find all crop files
        crop_files = sorted(event_dir.glob("*_crop.jpg"))
        
        for crop_file in crop_files:
            try:
                # Load image
                img = cv2.imread(str(crop_file))
                if img is None:
                    continue
                
                # Convert BGR to RGB
                img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                
                # Load metadata
                meta_file = crop_file.with_name(crop_file.stem.replace("_crop", "_meta") + ".json")
                metadata = {}
                if meta_file.exists():
                    with open(meta_file, 'r') as f:
                        metadata = json.load(f)
                
                # Parse timestamp from filename
                timestamp_str = crop_file.stem.replace("_crop", "")
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S_%f")
                
                frames.append((timestamp, img_rgb, metadata))
                
            except Exception as e:
                logger.warning(f"Failed to load frame {crop_file}: {e}")
                continue
        
        return frames
    
    def _resize_frame(self, frame: np.ndarray, max_width: int = None) -> np.ndarray:
        """Resize frame while maintaining aspect ratio"""
        max_width = max_width or config.alert.max_width
        
        height, width = frame.shape[:2]
        if width <= max_width:
            return frame
        
        # Calculate new dimensions
        aspect_ratio = height / width
        new_width = max_width
        new_height = int(new_width * aspect_ratio)
        
        # Resize
        resized = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)
        return resized
    
    def _decimate_frames(self, frames: List[Tuple[datetime, np.ndarray, dict]]) -> List[Tuple[datetime, np.ndarray, dict]]:
        """Reduce frame count to fit within limits"""
        if len(frames) <= config.alert.max_frames:
            return frames
        
        # Calculate decimation factor
        decimation = len(frames) / config.alert.max_frames
        
        # Select frames with even distribution
        selected_frames = []
        for i in range(config.alert.max_frames):
            index = int(i * decimation)
            if index < len(frames):
                selected_frames.append(frames[index])
        
        logger.info(f"Decimated {len(frames)} frames to {len(selected_frames)}")
        return selected_frames
    
    def build_gif(self, frames: List[Tuple[datetime, np.ndarray, dict]], output_path: Path) -> bool:
        """Build animated GIF from frames"""
        try:
            if not frames:
                logger.error("No frames provided for GIF creation")
                return False
            
            # Decimate frames if necessary
            frames = self._decimate_frames(frames)
            
            # Prepare PIL images
            pil_images = []
            for timestamp, frame, metadata in frames:
                # Resize frame
                resized_frame = self._resize_frame(frame)
                
                # Convert to PIL Image
                pil_img = Image.fromarray(resized_frame)
                pil_images.append(pil_img)
            
            # Calculate frame duration in milliseconds
            frame_duration = int(1000 / config.alert.target_fps)
            
            # Save as animated GIF
            pil_images[0].save(
                output_path,
                save_all=True,
                append_images=pil_images[1:],
                duration=frame_duration,
                loop=0,  # Infinite loop
                optimize=True
            )
            
            logger.info(f"Created GIF: {output_path} ({len(pil_images)} frames)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create GIF: {e}")
            return False
    
    def build_mp4(self, frames: List[Tuple[datetime, np.ndarray, dict]], output_path: Path) -> bool:
        """Build MP4 video from frames using ffmpeg"""
        try:
            if not frames:
                logger.error("No frames provided for MP4 creation")
                return False
            
            # Decimate frames if necessary
            frames = self._decimate_frames(frames)
            
            # Create temporary directory for frames
            temp_frames_dir = self.temp_dir / f"frames_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            temp_frames_dir.mkdir(exist_ok=True)
            
            # Save frames as individual images
            frame_paths = []
            for i, (timestamp, frame, metadata) in enumerate(frames):
                # Resize frame
                resized_frame = self._resize_frame(frame)
                
                # Convert RGB to BGR for OpenCV
                frame_bgr = cv2.cvtColor(resized_frame, cv2.COLOR_RGB2BGR)
                
                # Save frame
                frame_path = temp_frames_dir / f"frame_{i:04d}.jpg"
                cv2.imwrite(str(frame_path), frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, config.alert.quality])
                frame_paths.append(frame_path)
            
            # Build ffmpeg command
            ffmpeg_cmd = [
                "ffmpeg", "-y",  # Overwrite output
                "-framerate", str(config.alert.target_fps),
                "-i", str(temp_frames_dir / "frame_%04d.jpg"),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-crf", "23",  # Good quality
                str(output_path)
            ]
            
            # Run ffmpeg
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"Created MP4: {output_path} ({len(frames)} frames)")
                success = True
            else:
                logger.error(f"ffmpeg failed: {result.stderr}")
                success = False
            
            # Cleanup temporary frames
            for frame_path in frame_paths:
                frame_path.unlink(missing_ok=True)
            temp_frames_dir.rmdir()
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to create MP4: {e}")
            return False
    
    def build_from_recent_frames(self, frame_count: int = 10) -> Optional[Path]:
        """Build alert from recent motion frames"""
        try:
            # Find recent frame directories
            frames_base = config.get_frames_path()
            if not frames_base.exists():
                logger.error("Frames directory does not exist")
                return None
            
            # Get recent date directories
            date_dirs = sorted([d for d in frames_base.iterdir() if d.is_dir()], reverse=True)
            
            all_frames = []
            for date_dir in date_dirs:
                frames = self._load_frames_from_event(date_dir)
                all_frames.extend(frames)
                
                if len(all_frames) >= frame_count:
                    break
            
            # Take the most recent frames
            all_frames = sorted(all_frames, key=lambda x: x[0], reverse=True)[:frame_count]
            all_frames.reverse()  # Chronological order for playback
            
            if not all_frames:
                logger.error("No recent frames found")
                return None
            
            # Generate output filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if config.alert.output_format == "gif":
                output_path = self.temp_dir / f"recent_{timestamp}.gif"
                success = self.build_gif(all_frames, output_path)
            else:
                output_path = self.temp_dir / f"recent_{timestamp}.mp4"
                success = self.build_mp4(all_frames, output_path)
            
            return output_path if success else None
            
        except Exception as e:
            logger.error(f"Failed to build from recent frames: {e}")
            return None
    
    def build_from_event_dir(self, event_dir: Path) -> Optional[Path]:
        """Build alert from a specific event directory"""
        try:
            frames = self._load_frames_from_event(event_dir)
            
            if not frames:
                logger.error(f"No frames found in {event_dir}")
                return None
            
            # Generate output filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if config.alert.output_format == "gif":
                output_path = self.temp_dir / f"event_{timestamp}.gif"
                success = self.build_gif(frames, output_path)
            else:
                output_path = self.temp_dir / f"event_{timestamp}.mp4"
                success = self.build_mp4(frames, output_path)
            
            return output_path if success else None
            
        except Exception as e:
            logger.error(f"Failed to build from event directory: {e}")
            return None
    
    def cleanup_temp_files(self, max_age_hours: int = 24):
        """Clean up old temporary files"""
        try:
            import time
            current_time = time.time()
            max_age_seconds = max_age_hours * 3600
            
            for file_path in self.temp_dir.glob("*"):
                if file_path.is_file():
                    file_age = current_time - file_path.stat().st_mtime
                    if file_age > max_age_seconds:
                        file_path.unlink()
                        logger.debug(f"Cleaned up temp file: {file_path}")
                        
        except Exception as e:
            logger.error(f"Failed to cleanup temp files: {e}")


def main():
    """Main entry point for GIF builder service"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="TurtleCam GIF/Video Builder")
    parser.add_argument("--frames", "-f", type=int, default=10, help="Number of recent frames to use")
    parser.add_argument("--event-dir", "-e", type=str, help="Specific event directory to process")
    parser.add_argument("--output", "-o", type=str, help="Output file path")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, config.system.log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    builder = AlertBuilder()
    
    try:
        if args.event_dir:
            # Build from specific event directory
            event_path = Path(args.event_dir)
            output_path = builder.build_from_event_dir(event_path)
        else:
            # Build from recent frames
            output_path = builder.build_from_recent_frames(args.frames)
        
        if output_path:
            if args.output:
                # Move to specified output location
                final_path = Path(args.output)
                final_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.rename(final_path)
                print(f"Alert created: {final_path}")
            else:
                print(f"Alert created: {output_path}")
        else:
            print("Failed to create alert")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"GIF builder error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
