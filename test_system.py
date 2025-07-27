#!/usr/bin/env python3
"""
TurtleCam System Test Script
Quick validation of configuration and components without requiring hardware.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

def test_imports():
    """Test that all required modules can be imported"""
    print("🔍 Testing imports...")
    
    try:
        import cv2
        print(f"  ✅ OpenCV: {cv2.__version__}")
    except ImportError as e:
        print(f"  ❌ OpenCV: {e}")
        return False
    
    try:
        import numpy as np
        print(f"  ✅ NumPy: {np.__version__}")
    except ImportError as e:
        print(f"  ❌ NumPy: {e}")
        return False
    
    try:
        from PIL import Image
        print(f"  ✅ Pillow: {Image.__version__}")
    except ImportError as e:
        print(f"  ❌ Pillow: {e}")
        return False
    
    try:
        import telegram
        print(f"  ✅ python-telegram-bot: {telegram.__version__}")
    except ImportError as e:
        print(f"  ❌ python-telegram-bot: {e}")
        return False
    
    try:
        import psutil
        print(f"  ✅ psutil: {psutil.__version__}")
    except ImportError as e:
        print(f"  ❌ psutil: {e}")
        return False
    
    return True

def test_config():
    """Test configuration loading and validation"""
    print("\n⚙️ Testing configuration...")
    
    try:
        from config import config
        print("  ✅ Configuration module loaded")
        
        # Test validation
        errors = config.validate()
        if errors:
            print(f"  ⚠️ Configuration validation errors:")
            for error in errors:
                print(f"    - {error}")
        else:
            print("  ✅ Configuration validation passed")
        
        # Test path creation
        print(f"  📁 Frames path: {config.get_frames_path()}")
        print(f"  📁 Archives path: {config.get_archives_path()}")
        print(f"  📁 Database path: {config.get_database_path()}")
        
        if config.storage.save_ml_frames:
            ml_path = config.get_ml_frames_path()
            print(f"  📁 ML frames path: {ml_path}")
        
        return len(errors) == 0
        
    except Exception as e:
        print(f"  ❌ Configuration error: {e}")
        return False

def test_database():
    """Test database initialization"""
    print("\n🗄️ Testing database...")
    
    try:
        from database import DatabaseManager, Detection
        from datetime import datetime
        
        # Use temporary database for testing
        test_db_path = Path("/tmp/test_turtle.db")
        if test_db_path.exists():
            test_db_path.unlink()
        
        db = DatabaseManager(test_db_path)
        print("  ✅ Database initialized")
        
        # Test insertion
        test_detection = Detection(
            timestamp=datetime.now(),
            bbox_x=100,
            bbox_y=100,
            bbox_w=200,
            bbox_h=150,
            confidence=0.95,
            img_path="/tmp/test.jpg"
        )
        
        success = db.insert_detection(test_detection)
        if success:
            print("  ✅ Detection insertion test passed")
        else:
            print("  ❌ Detection insertion test failed")
            return False
        
        # Test retrieval
        recent = db.get_recent_detections(1)
        if len(recent) == 1:
            print("  ✅ Detection retrieval test passed")
        else:
            print("  ❌ Detection retrieval test failed")
            return False
        
        # Cleanup
        test_db_path.unlink()
        print("  ✅ Database test cleanup completed")
        
        return True
        
    except Exception as e:
        print(f"  ❌ Database error: {e}")
        return False

def test_gif_builder():
    """Test GIF builder without camera"""
    print("\n🎬 Testing GIF builder...")
    
    try:
        from gif_builder import AlertBuilder
        import numpy as np
        
        builder = AlertBuilder()
        print("  ✅ AlertBuilder initialized")
        
        # Create test frames
        test_frames = []
        for i in range(5):
            # Create a simple test image
            img = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
            timestamp = datetime.now()
            metadata = {"test": True}
            test_frames.append((timestamp, img, metadata))
        
        print(f"  ✅ Created {len(test_frames)} test frames")
        
        # Test frame decimation
        decimated = builder._decimate_frames(test_frames)
        print(f"  ✅ Frame decimation test: {len(test_frames)} -> {len(decimated)}")
        
        # Test frame resizing
        resized = builder._resize_frame(test_frames[0][1], max_width=320)
        print(f"  ✅ Frame resize test: {test_frames[0][1].shape} -> {resized.shape}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ GIF builder error: {e}")
        return False

def test_telegram_config():
    """Test Telegram configuration"""
    print("\n📱 Testing Telegram configuration...")
    
    try:
        from config import config
        
        if not config.telegram.bot_token:
            print("  ⚠️ TELEGRAM_BOT_TOKEN not set")
            return False
        
        if not config.telegram.chat_id:
            print("  ⚠️ TELEGRAM_CHAT_ID not set")
            return False
        
        print("  ✅ Telegram credentials configured")
        
        # Test bot token format
        if not config.telegram.bot_token.count(':') == 1:
            print("  ⚠️ Bot token format may be incorrect")
            return False
        
        print("  ✅ Bot token format looks valid")
        
        # Test chat ID format
        try:
            int(config.telegram.chat_id)
            print("  ✅ Chat ID format looks valid")
        except ValueError:
            print("  ⚠️ Chat ID should be numeric")
            return False
        
        return True
        
    except Exception as e:
        print(f"  ❌ Telegram config error: {e}")
        return False

def test_system_requirements():
    """Test system requirements and capabilities"""
    print("\n🖥️ Testing system requirements...")
    
    try:
        import psutil
        
        # Check available memory
        memory = psutil.virtual_memory()
        memory_gb = memory.total / (1024**3)
        print(f"  💾 Total RAM: {memory_gb:.1f} GB")
        
        if memory_gb < 3.5:  # Account for GPU memory split
            print("  ⚠️ Low memory - consider optimizing settings")
        else:
            print("  ✅ Sufficient memory available")
        
        # Check available disk space
        disk = psutil.disk_usage('/')
        disk_gb = disk.free / (1024**3)
        print(f"  💽 Free disk space: {disk_gb:.1f} GB")
        
        if disk_gb < 10:
            print("  ⚠️ Low disk space - enable aggressive cleanup")
        else:
            print("  ✅ Sufficient disk space available")
        
        # Check CPU
        cpu_count = psutil.cpu_count()
        print(f"  🔧 CPU cores: {cpu_count}")
        
        return True
        
    except Exception as e:
        print(f"  ❌ System requirements error: {e}")
        return False

def main():
    """Run all system tests"""
    print("🐢 TurtleCam System Test")
    print("=" * 50)
    
    tests = [
        ("Imports", test_imports),
        ("Configuration", test_config),
        ("Database", test_database),
        ("GIF Builder", test_gif_builder),
        ("Telegram Config", test_telegram_config),
        ("System Requirements", test_system_requirements),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"  ❌ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    print("\n" + "=" * 50)
    print("📊 Test Results Summary")
    print("=" * 50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} {test_name}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! System ready for deployment.")
        return 0
    else:
        print("⚠️ Some tests failed. Check configuration and dependencies.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
