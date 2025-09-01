#!/bin/bash
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
