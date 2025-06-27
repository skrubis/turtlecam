"""YOLO Export module for TurtleCam.

This module exports captured turtle images and metadata in YOLO format for
machine learning training. It supports both YOLOv5 and YOLOv8 formats.
"""

import os
import logging
import argparse
import sqlite3
import shutil
import random
import json
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple

# Try to import PIL for image operations
try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    logging.warning("PIL not available, image operations limited")

# Try to import tqdm for progress bars
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

logger = logging.getLogger(__name__)


class YOLOExporter:
    """Exports TurtleCam data in YOLO format for ML training."""
    
    def __init__(self, 
                 db_path="data/turtlecam.db",
                 image_dir="data/images",
                 export_dir="export",
                 yolo_version=8,
                 class_map=None):
        """Initialize YOLO exporter.
        
        Args:
            db_path (str): Path to SQLite database
            image_dir (str): Base path to image directory
            export_dir (str): Directory for exported data
            yolo_version (int): YOLO version (5 or 8)
            class_map (dict, optional): Custom class mapping
        """
        self.db_path = Path(db_path)
        self.image_dir = Path(image_dir)
        self.export_dir = Path(export_dir)
        self.yolo_version = yolo_version
        
        # Set up class mapping - default is just "turtle"
        self.class_map = class_map or {"turtle": 0}
        
        # Validate requirements
        if not PIL_AVAILABLE:
            raise ImportError("PIL (Pillow) is required for YOLO export")
            
        # Ensure DB exists
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found: {self.db_path}")
    
    def export(self, 
              start_date=None, 
              end_date=None,
              limit=None,
              train_split=0.8,
              val_split=0.1,
              random_seed=42,
              include_empty=False,
              target_size=None,
              normalize=True):
        """Export data in YOLO format.
        
        Args:
            start_date (datetime, optional): Start date for export
            end_date (datetime, optional): End date for export
            limit (int, optional): Maximum crops to export
            train_split (float): Ratio for training set
            val_split (float): Ratio for validation set
            random_seed (int): Random seed for reproducible splits
            include_empty (bool): Include frames with no detections
            target_size (tuple, optional): Target image size (width, height)
            normalize (bool): Normalize coordinates to [0-1]
            
        Returns:
            dict: Export statistics
        """
        try:
            # Prepare for export
            random.seed(random_seed)
            stats = {
                "timestamp": datetime.now().isoformat(),
                "yolo_version": self.yolo_version,
                "total_crops": 0,
                "train_crops": 0, 
                "val_crops": 0,
                "test_crops": 0,
                "skipped_crops": 0,
                "classes": list(self.class_map.keys())
            }
            
            # Create export directory structure
            self._create_export_dirs()
            
            # Fetch crops from database
            crops = self._fetch_crops(start_date, end_date, limit, include_empty)
            total_crops = len(crops)
            stats["total_crops"] = total_crops
            
            if total_crops == 0:
                logger.warning("No crops found matching criteria")
                return stats
                
            # Split data into train/val/test sets
            random.shuffle(crops)
            train_idx = int(total_crops * train_split)
            val_idx = int(total_crops * (train_split + val_split))
            
            train_crops = crops[:train_idx]
            val_crops = crops[train_idx:val_idx]
            test_crops = crops[val_idx:]
            
            # Export each dataset
            stats["train_crops"] = self._export_dataset("train", train_crops, target_size, normalize)
            stats["val_crops"] = self._export_dataset("val", val_crops, target_size, normalize)
            stats["test_crops"] = self._export_dataset("test", test_crops, target_size, normalize)
            stats["skipped_crops"] = total_crops - sum([stats["train_crops"], stats["val_crops"], stats["test_crops"]])
            
            # Create dataset config file
            self._create_dataset_config()
            
            # Save export metadata
            self._save_export_metadata(stats)
            
            logger.info(f"Export complete. Total: {total_crops} crops, "
                      f"Train: {stats['train_crops']}, "
                      f"Val: {stats['val_crops']}, "
                      f"Test: {stats['test_crops']}")
                      
            return stats
            
        except Exception as e:
            logger.error(f"Error during export: {e}", exc_info=True)
            return {"error": str(e)}
    
    def _create_export_dirs(self):
        """Create export directory structure."""
        # Create main export directory
        self.export_dir.mkdir(parents=True, exist_ok=True)
        
        # Create dataset directories
        for dataset in ["train", "val", "test"]:
            dataset_dir = self.export_dir / dataset
            dataset_dir.mkdir(exist_ok=True)
            
            # Create images and labels directories
            img_dir = dataset_dir / "images"
            label_dir = dataset_dir / "labels"
            img_dir.mkdir(exist_ok=True)
            label_dir.mkdir(exist_ok=True)
    
    def _fetch_crops(self, start_date, end_date, limit, include_empty):
        """Fetch crop data from database.
        
        Args:
            start_date (datetime): Start date filter
            end_date (datetime): End date filter
            limit (int): Maximum crops to fetch
            include_empty (bool): Include frames with no detections
            
        Returns:
            list: List of crop records
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Build query
            query = """
            SELECT 
                c.id, c.event_id, c.timestamp, c.crop_path,
                c.x, c.y, c.width, c.height, c.confidence, c.label,
                e.gif_path, e.metadata
            FROM 
                crops c
            LEFT JOIN 
                motion_events e ON c.event_id = e.id
            WHERE 
                1=1
            """
            params = []
            
            # Add date filters
            if start_date:
                query += " AND c.timestamp >= ?"
                params.append(start_date.isoformat())
                
            if end_date:
                query += " AND c.timestamp <= ?"
                params.append(end_date.isoformat())
                
            # Handle empty frames differently if requested
            if not include_empty:
                query += " AND c.width > 0 AND c.height > 0"
                
            # Order and limit
            query += " ORDER BY c.timestamp"
            
            if limit and limit > 0:
                query += " LIMIT ?"
                params.append(limit)
                
            # Execute query
            cursor.execute(query, params)
            crops = [dict(row) for row in cursor.fetchall()]
            
            conn.close()
            logger.info(f"Fetched {len(crops)} crops from database")
            return crops
            
        except Exception as e:
            logger.error(f"Error fetching crops: {e}")
            return []
    
    def _export_dataset(self, dataset_name, crops, target_size, normalize):
        """Export a dataset split.
        
        Args:
            dataset_name (str): Dataset name (train/val/test)
            crops (list): List of crops to export
            target_size (tuple): Target image size (width, height)
            normalize (bool): Normalize coordinates to [0-1]
            
        Returns:
            int: Number of successfully exported crops
        """
        if not crops:
            return 0
            
        # Set up paths
        img_dir = self.export_dir / dataset_name / "images"
        label_dir = self.export_dir / dataset_name / "labels"
        
        exported_count = 0
        
        # Progress bar if available
        if TQDM_AVAILABLE:
            crops_iter = tqdm(crops, desc=f"Exporting {dataset_name}")
        else:
            crops_iter = crops
            logger.info(f"Exporting {len(crops)} crops for {dataset_name}")
        
        # Process each crop
        for idx, crop in enumerate(crops_iter):
            try:
                crop_path = crop["crop_path"]
                if not crop_path:
                    continue
                
                # Convert to Path object if it's a string
                if isinstance(crop_path, str):
                    crop_path = Path(crop_path)
                
                # Check if file exists
                if not crop_path.exists():
                    logger.warning(f"Crop file not found: {crop_path}")
                    continue
                
                # Generate target filenames
                base_name = f"{dataset_name}_{idx:06d}"
                img_filename = f"{base_name}.jpg"
                label_filename = f"{base_name}.txt"
                
                img_path = img_dir / img_filename
                label_path = label_dir / label_filename
                
                # Copy and resize image if needed
                self._process_image(crop_path, img_path, target_size)
                
                # Create YOLO label file
                self._create_label_file(crop, img_path, label_path, normalize)
                
                exported_count += 1
                
            except Exception as e:
                logger.error(f"Error exporting crop {crop.get('id')}: {e}")
        
        return exported_count
    
    def _process_image(self, src_path, dst_path, target_size):
        """Process and save image for YOLO.
        
        Args:
            src_path (Path): Source image path
            dst_path (Path): Destination image path
            target_size (tuple): Target size (width, height) or None
        """
        if not target_size:
            # Simple copy if no resizing needed
            shutil.copy2(src_path, dst_path)
            return
            
        # Resize image
        with Image.open(src_path) as img:
            # Get original size
            orig_width, orig_height = img.size
            
            # Resize
            resized_img = img.resize(target_size, Image.Resampling.LANCZOS)
            
            # Save
            resized_img.save(dst_path, quality=90)
    
    def _create_label_file(self, crop, img_path, label_path, normalize):
        """Create YOLO format label file.
        
        Args:
            crop (dict): Crop record
            img_path (Path): Image file path
            label_path (Path): Label file path
            normalize (bool): Normalize coordinates to [0-1]
        """
        try:
            # Get image dimensions
            with Image.open(img_path) as img:
                img_width, img_height = img.size
                
            # Get bounding box coordinates
            x = crop["x"] or 0
            y = crop["y"] or 0
            width = crop["width"] or 0
            height = crop["height"] or 0
            
            # Skip if no valid bounding box
            if width <= 0 or height <= 0:
                # Create empty label file for consistency
                with open(label_path, 'w') as f:
                    pass
                return
            
            # Get class id - default to 0 if not mapped
            label = crop["label"] or "turtle"
            class_id = self.class_map.get(label.lower(), 0)
            
            # Calculate YOLO format (center_x, center_y, width, height)
            center_x = x + width / 2
            center_y = y + height / 2
            
            # Normalize if requested
            if normalize:
                center_x /= img_width
                center_y /= img_height
                width /= img_width
                height /= img_height
            
            # Ensure values are within bounds [0-1]
            center_x = max(0.0, min(1.0, center_x)) if normalize else center_x
            center_y = max(0.0, min(1.0, center_y)) if normalize else center_y
            width = max(0.001, min(1.0, width)) if normalize else width
            height = max(0.001, min(1.0, height)) if normalize else height
            
            # Write label file
            with open(label_path, 'w') as f:
                f.write(f"{class_id} {center_x:.6f} {center_y:.6f} {width:.6f} {height:.6f}\n")
                
        except Exception as e:
            logger.error(f"Error creating label file for crop {crop.get('id')}: {e}")
            # Create empty label file for consistency
            with open(label_path, 'w') as f:
                pass
    
    def _create_dataset_config(self):
        """Create YOLO dataset configuration file."""
        try:
            # Create dataset.yaml config file for YOLOv5/v8
            config = {
                "path": str(self.export_dir.absolute()),
                "train": "train/images",
                "val": "val/images",
                "test": "test/images",
                "nc": len(self.class_map),
                "names": list(self.class_map.keys())
            }
            
            # Save config
            config_path = self.export_dir / "dataset.yaml"
            with open(config_path, 'w') as f:
                yaml.dump(config, f, default_flow_style=False)
                
            logger.info(f"Created dataset config at {config_path}")
            
        except Exception as e:
            logger.error(f"Error creating dataset config: {e}")
    
    def _save_export_metadata(self, stats):
        """Save export metadata.
        
        Args:
            stats (dict): Export statistics
        """
        try:
            # Add additional metadata
            stats["export_dir"] = str(self.export_dir.absolute())
            stats["db_path"] = str(self.db_path)
            stats["yolo_version"] = self.yolo_version
            stats["class_map"] = self.class_map
            
            # Save as JSON
            metadata_path = self.export_dir / "export_metadata.json"
            with open(metadata_path, 'w') as f:
                json.dump(stats, f, indent=2)
                
            logger.info(f"Saved export metadata to {metadata_path}")
            
        except Exception as e:
            logger.error(f"Error saving export metadata: {e}")


def main():
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="TurtleCam YOLO Export")
    parser.add_argument("--db", default="data/turtlecam.db", help="Path to database")
    parser.add_argument("--images", default="data/images", help="Path to images directory")
    parser.add_argument("--output", default="export", help="Export directory")
    parser.add_argument("--yolo-version", type=int, default=8, choices=[5, 8], help="YOLO version")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--limit", type=int, help="Maximum crops to export")
    parser.add_argument("--train", type=float, default=0.8, help="Train split ratio")
    parser.add_argument("--val", type=float, default=0.1, help="Validation split ratio")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--include-empty", action="store_true", help="Include frames with no detections")
    parser.add_argument("--width", type=int, help="Target image width")
    parser.add_argument("--height", type=int, help="Target image height")
    parser.add_argument("--no-normalize", action="store_true", help="Don't normalize coordinates")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Parse dates if provided
    start_date = None
    end_date = None
    
    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    
    # Set target size if provided
    target_size = None
    if args.width and args.height:
        target_size = (args.width, args.height)
    
    # Create exporter
    exporter = YOLOExporter(
        db_path=args.db,
        image_dir=args.images,
        export_dir=args.output,
        yolo_version=args.yolo_version
    )
    
    # Run export
    stats = exporter.export(
        start_date=start_date,
        end_date=end_date,
        limit=args.limit,
        train_split=args.train,
        val_split=args.val,
        random_seed=args.seed,
        include_empty=args.include_empty,
        target_size=target_size,
        normalize=not args.no_normalize
    )
    
    # Print summary
    print(f"Export complete:")
    print(f"  Total crops: {stats['total_crops']}")
    print(f"  Train crops: {stats['train_crops']}")
    print(f"  Val crops: {stats['val_crops']}")
    print(f"  Test crops: {stats['test_crops']}")
    print(f"  Classes: {', '.join(stats['classes'])}")
    print(f"  Export directory: {args.output}")


if __name__ == "__main__":
    main()
