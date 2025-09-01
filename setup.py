#!/usr/bin/env python3
"""
Automatic Setup Script for Bybit Options Tracker
Installs all dependencies and verifies the environment
"""

import subprocess
import sys
import os
from pathlib import Path

def print_banner():
    """Print setup banner"""
    print("="*60)
    print("🚀 Bybit Options Tracker - Setup Script")
    print("="*60)

def check_python_version():
    """Check if Python version is 3.7+"""
    print("\n📌 Checking Python version...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 7):
        print(f"❌ Python 3.7+ required, you have {version.major}.{version.minor}")
        sys.exit(1)
    print(f"✅ Python {version.major}.{version.minor}.{version.micro} detected")

def install_packages():
    """Install required packages"""
    print("\n📦 Installing required packages...")
    
    packages = {
        'redis': '5.0.1',
        'pybit': '5.6.2', 
        'requests': '2.31.0',
        'hiredis': '2.3.2'  # Optional but recommended
    }
    
    for package, version in packages.items():
        try:
            print(f"  Installing {package}=={version}...")
            subprocess.check_call([
                sys.executable, '-m', 'pip', 'install', 
                f'{package}=={version}', '--quiet'
            ])
            print(f"  ✅ {package} installed")
        except subprocess.CalledProcessError:
            if package == 'hiredis':
                print(f"  ⚠️  {package} installation failed (optional, continuing...)")
            else:
                print(f"  ❌ Failed to install {package}")
                sys.exit(1)

def verify_imports():
    """Verify all imports work"""
    print("\n🔍 Verifying imports...")
    
    try:
        import redis
        print("  ✅ redis imported successfully")
        
        import pybit
        print("  ✅ pybit imported successfully")
        
        import requests
        print("  ✅ requests imported successfully")
        
        try:
            import hiredis
            print("  ✅ hiredis imported (performance boost enabled)")
        except ImportError:
            print("  ⚠️  hiredis not available (optional)")
            
        return True
        
    except ImportError as e:
        print(f"  ❌ Import failed: {e}")
        return False

def check_redis_server():
    """Check if Redis server is available"""
    print("\n🔍 Checking Redis server...")
    
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, socket_connect_timeout=1)
        r.ping()
        print("  ✅ Redis server is running on localhost:6379")
        return True
    except:
        print("  ⚠️  Redis server not running")
        print("\n  To install Redis:")
        
        if sys.platform == "darwin":
            print("    macOS: brew install redis && brew services start redis")
        elif sys.platform.startswith("linux"):
            print("    Linux: sudo apt-get install redis-server")
            print("           sudo systemctl start redis")
        elif sys.platform == "win32":
            print("    Windows: Download from https://github.com/microsoftarchive/redis/releases")
        
        print("\n  To start Redis manually: redis-server")
        return False

def test_bybit_connection():
    """Test connection to Bybit API"""
    print("\n🌐 Testing Bybit API connection...")
    
    try:
        import requests
        response = requests.get(
            "https://api.bybit.com/v5/market/time",
            timeout=5
        )
        if response.status_code == 200:
            print("  ✅ Bybit API is accessible")
            return True
        else:
            print("  ⚠️  Bybit API returned status:", response.status_code)
            return False
    except Exception as e:
        print(f"  ❌ Cannot reach Bybit API: {e}")
        return False

def create_start_script():
    """Create a simple start script"""
    print("\n📝 Creating start script...")
    
    start_script = """#!/bin/bash
# Start script for Bybit Options Tracker

echo "Starting Bybit Options Tracker..."

# Check if Redis is running
redis-cli ping > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "❌ Redis is not running. Starting Redis..."
    redis-server --daemonize yes
    sleep 2
fi

# Run the tracker
python3 bybit_options_optimized.py track
"""
    
    script_path = Path("start.sh")
    script_path.write_text(start_script)
    script_path.chmod(0o755)
    print("  ✅ Created start.sh script")

def main():
    """Main setup function"""
    print_banner()
    
    # Check Python version
    check_python_version()
    
    # Install packages
    install_packages()
    
    # Verify imports
    if not verify_imports():
        print("\n❌ Setup failed: Import verification failed")
        sys.exit(1)
    
    # Check Redis
    redis_ok = check_redis_server()
    
    # Test Bybit connection
    bybit_ok = test_bybit_connection()
    
    # Create start script
    create_start_script()
    
    # Final summary
    print("\n" + "="*60)
    print("📊 Setup Summary")
    print("="*60)
    print(f"  Python:        ✅ Ready")
    print(f"  Dependencies:  ✅ Installed")
    print(f"  Redis Server:  {'✅ Running' if redis_ok else '⚠️  Not running (required)'}")
    print(f"  Bybit API:     {'✅ Accessible' if bybit_ok else '⚠️  Not accessible'}")
    
    print("\n🎯 Next Steps:")
    if not redis_ok:
        print("  1. Start Redis: redis-server")
    print(f"  {'2' if not redis_ok else '1'}. Run tracker: python3 bybit_options_optimized.py track")
    print(f"  {'3' if not redis_ok else '2'}. Or use: ./start.sh")
    
    print("\n✅ Setup complete!")
    
    # Quick test import
    print("\n🧪 Quick test of tracker...")
    try:
        import bybit_options_optimized
        print("  ✅ Tracker module loads successfully")
    except ImportError as e:
        print(f"  ⚠️  Warning: {e}")
    except Exception as e:
        print(f"  ⚠️  Note: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Setup interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Setup failed with error: {e}")
        sys.exit(1)