"""
Optimized Bybit Options Tracker - High Performance Version
Improvements:
- Redis connection pooling
- Batch processing for Redis writes
- Optimized WebSocket settings
- Better error handling and reconnection
- Memory efficient data structures
- Performance monitoring
"""

import asyncio
import json
import redis
import requests
import sys
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
from pybit.unified_trading import WebSocket
from collections import deque
from threading import Lock
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OptimizedOptionsTracker:
    def __init__(self, 
                 cache_file="symbols_cache.json",
                 redis_host="localhost",
                 redis_port=6379,
                 redis_db=0,
                 redis_password=None):
        
        # Core settings
        self.cache_file = cache_file
        self.cache_duration_hours = 24
        self.known_option_assets = ['BTC', 'ETH', 'SOL']
        self.api_url = "https://api.bybit.com/v5/market/instruments-info"
        
        # Redis settings with connection pooling
        self.redis_pool = redis.ConnectionPool(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            max_connections=50,
            socket_keepalive=True,
            socket_keepalive_options={
                1: 1,  # TCP_KEEPIDLE
                2: 1,  # TCP_KEEPINTVL  
                3: 5,  # TCP_KEEPCNT
            },
            decode_responses=True
        )
        self.redis_client = None
        self.ws = None
        
        # Optimization settings
        self.batch_size = 200  # Increased from 100
        self.batch_timeout = 2.0  # Reduced from 5.0
        self.batch_queue = deque(maxlen=10000)
        self.batch_lock = Lock()
        self.last_batch_time = time.time()
        
        # WebSocket optimization
        self.ws_ping_interval = 45  # Increased from default 30
        self.ws_ping_timeout = 15   # Must be less than ping_interval
        self.ws_reconnect_delay = 10  # Increased from 5
        self.ws_max_reconnect_attempts = 10
        self.ws_reconnect_count = 0
        
        # Performance stats
        self.stats = {
            'messages': 0,
            'errors': 0,
            'batches': 0,
            'last_update': None,
            'msg_per_sec': 0,
            'last_msg_count': 0,
            'last_msg_time': time.time()
        }
        
        # Memory optimization
        self.symbol_chunks = []
        self.active_symbols = set()

    # ==================== SYMBOL FETCHING METHODS ====================
    
    def load_cache(self):
        """Load symbols from cache if valid"""
        cache_path = Path(self.cache_file)
        
        if not cache_path.exists():
            logger.info("No cache file found")
            return None
        
        try:
            with open(cache_path, 'r') as f:
                cache_data = json.load(f)
            
            cached_time = datetime.fromisoformat(cache_data['updated_at'])
            expires_at = datetime.fromisoformat(cache_data['expires_at'])
            age_hours = (datetime.now() - cached_time).total_seconds() / 3600
            
            if datetime.now() > expires_at:
                logger.info(f"Cache expired (age: {age_hours:.1f} hours)")
                return None
            
            logger.info(f"Loaded {cache_data['count']} symbols from cache (age: {age_hours:.1f}h)")
            return cache_data['symbols']
            
        except Exception as e:
            logger.error(f"Error reading cache: {e}")
            return None

    def save_cache(self, symbols):
        """Save symbols to cache with metadata"""
        cache_data = {
            'symbols': symbols,
            'count': len(symbols),
            'updated_at': datetime.now().isoformat(),
            'expires_at': (datetime.now() + timedelta(hours=self.cache_duration_hours)).isoformat(),
            'by_asset': {
                'BTC': len([s for s in symbols if s.startswith('BTC-')]),
                'ETH': len([s for s in symbols if s.startswith('ETH-')]),
                'SOL': len([s for s in symbols if s.startswith('SOL-')])
            }
        }
        
        with open(self.cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        
        logger.info(f"Saved {len(symbols)} symbols to cache")

    def fetch_from_api(self):
        """Fetch symbols from Bybit API with retry logic"""
        logger.info("Fetching fresh symbols from API...")
        
        all_tickers = []
        retry_count = 3
        
        for coin in self.known_option_assets:
            cursor = None
            coin_count = 0
            
            while True:
                params = {"category": "option", "baseCoin": coin, "limit": 1000}
                if cursor:
                    params["cursor"] = cursor
                
                for attempt in range(retry_count):
                    try:
                        response = requests.get(self.api_url, params=params, timeout=10)
                        data = response.json()
                        
                        if data.get("retCode") != 0:
                            break
                        
                        items = data.get("result", {}).get("list", [])
                        if not items:
                            break
                        
                        # Only get actively trading symbols
                        symbols = [
                            item["symbol"]
                            for item in items
                            if item.get("status") == "Trading"
                        ]
                        all_tickers.extend(symbols)
                        coin_count += len(symbols)
                        
                        cursor = data.get("result", {}).get("nextPageCursor")
                        if not cursor:
                            break
                        
                        break  # Success, exit retry loop
                        
                    except Exception as e:
                        if attempt == retry_count - 1:
                            logger.error(f"Failed to fetch {coin} after {retry_count} attempts: {e}")
                            break
                        time.sleep(1)  # Wait before retry
                
                if not cursor:
                    break
            
            if coin_count > 0:
                logger.info(f"  {coin}: {coin_count} options")
        
        logger.info(f"Total fetched: {len(all_tickers)} symbols")
        return all_tickers

    def get_symbols(self, force_refresh=False):
        """Get symbols from cache or API"""
        if force_refresh:
            symbols = self.fetch_from_api()
            if symbols:
                self.save_cache(symbols)
            return symbols
        
        symbols = self.load_cache()
        if symbols:
            return symbols
        
        symbols = self.fetch_from_api()
        if symbols:
            self.save_cache(symbols)
        
        return symbols

    # ==================== REDIS OPTIMIZATION ====================
    
    def init_redis(self):
        """Initialize Redis with connection pooling"""
        try:
            self.redis_client = redis.Redis(connection_pool=self.redis_pool)
            self.redis_client.ping()
            
            # Get Redis info
            info = self.redis_client.info()
            logger.info(f"Redis connected (v{info.get('redis_version', 'unknown')})")
            
            # Start batch processor
            asyncio.create_task(self.batch_processor())
            
            return True
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            return False

    def clear_database(self):
        """Clear Redis database on startup"""
        try:
            if self.redis_client:
                self.redis_client.flushdb()
                logger.info("Redis database cleared")
        except Exception as e:
            logger.error(f"Error clearing Redis: {e}")

    async def batch_processor(self):
        """Process Redis writes in batches for efficiency"""
        logger.info("Batch processor started")
        
        while True:
            try:
                await asyncio.sleep(self.batch_timeout)
                
                with self.batch_lock:
                    if not self.batch_queue:
                        continue
                    
                    # Process batch
                    batch_size = min(len(self.batch_queue), self.batch_size)
                    batch = [self.batch_queue.popleft() for _ in range(batch_size)]
                
                if batch:
                    # Use pipeline for batch writes
                    pipe = self.redis_client.pipeline(transaction=False)
                    
                    for item in batch:
                        symbol = item['symbol']
                        data = item['data']
                        
                        hash_key = f"option:{symbol}"
                        pipe.hset(hash_key, mapping=data)
                        pipe.expire(hash_key, 86400)
                    
                    # Update stats
                    pipe.hincrby("stats", "messages", len(batch))
                    pipe.hset("stats", "last_update", str(time.time()))
                    pipe.hincrby("stats", "batches", 1)
                    
                    # Execute batch
                    pipe.execute()
                    
                    self.stats['batches'] += 1
                    
                    if self.stats['batches'] % 10 == 0:
                        logger.info(f"Processed batch #{self.stats['batches']}: {len(batch)} items")
                        
            except Exception as e:
                logger.error(f"Batch processor error: {e}")
                await asyncio.sleep(1)

    # ==================== WEBSOCKET OPTIMIZATION ====================
    
    def handle_message(self, message):
        """Handle WebSocket messages with batch queuing"""
        try:
            self.stats['messages'] += 1
            
            data = message.get("data")
            if not data:
                return
            
            symbol = data.get('symbol')
            if not symbol:
                return
            
            # Prepare optimized record
            record = {
                'ts': int(time.time()),  # Shorter key, integer timestamp
                'biv': self._to_float(data.get('bidIv')),
                'aiv': self._to_float(data.get('askIv')),
                'lp': self._to_float(data.get('lastPrice')),
                'mp': self._to_float(data.get('markPrice')),
                'ip': self._to_float(data.get('indexPrice')),
                'miv': self._to_float(data.get('markPriceIv')),
                'up': self._to_float(data.get('underlyingPrice')),
                'oi': self._to_float(data.get('openInterest')),
                'd': self._to_float(data.get('delta')),
                'g': self._to_float(data.get('gamma')),
                'v': self._to_float(data.get('vega')),
                't': self._to_float(data.get('theta')),
                'v24': self._to_float(data.get('volume24h')),
                't24': self._to_float(data.get('turnover24h')),
            }
            
            # Remove None values to save space
            record = {k: str(v) for k, v in record.items() if v is not None}
            
            # Add to batch queue
            with self.batch_lock:
                self.batch_queue.append({
                    'symbol': symbol,
                    'data': record
                })
            
            self.stats['last_update'] = datetime.now()
            
            # Calculate messages per second
            current_time = time.time()
            time_diff = current_time - self.stats['last_msg_time']
            if time_diff >= 5:  # Update every 5 seconds
                msg_diff = self.stats['messages'] - self.stats['last_msg_count']
                self.stats['msg_per_sec'] = msg_diff / time_diff
                self.stats['last_msg_count'] = self.stats['messages']
                self.stats['last_msg_time'] = current_time
            
            # Show progress
            if self.stats['messages'] % 1000 == 0:
                logger.info(
                    f"Messages: {self.stats['messages']:,} | "
                    f"Rate: {self.stats['msg_per_sec']:.0f}/s | "
                    f"Queue: {len(self.batch_queue)} | "
                    f"Errors: {self.stats['errors']}"
                )
                
        except Exception as e:
            self.stats['errors'] += 1
            if self.stats['errors'] % 100 == 0:
                logger.error(f"Message handling error: {e}")

    def _to_float(self, value):
        """Optimized float conversion"""
        if value is None or value == '':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def subscribe_symbols(self, symbols):
        """Subscribe with optimized WebSocket settings"""
        # Custom WebSocket with optimized settings
        self.ws = WebSocket(
            testnet=False,
            channel_type="option",
            ping_interval=self.ws_ping_interval,
            ping_timeout=self.ws_ping_timeout,
            max_size=2**23,  # 8MB buffer
            compression=None  # Disable compression for speed
        )
        
        # Store symbols for reconnection
        self.active_symbols = set(symbols)
        
        # Subscribe in optimized chunks
        chunk_size = 100  # Increased from 50
        self.symbol_chunks = [list(symbols)[i:i + chunk_size] 
                             for i in range(0, len(symbols), chunk_size)]
        
        logger.info(f"Subscribing to {len(symbols)} symbols in {len(self.symbol_chunks)} batches...")
        
        for i, chunk in enumerate(self.symbol_chunks):
            try:
                self.ws.ticker_stream(
                    symbol=chunk,
                    callback=self.handle_message
                )
                logger.info(f"  Batch {i + 1}/{len(self.symbol_chunks)}: {len(chunk)} symbols")
                time.sleep(0.1)  # Reduced delay
                
            except Exception as e:
                logger.error(f"Subscription error batch {i + 1}: {e}")
                self.ws_reconnect_count += 1
                
                if self.ws_reconnect_count < self.ws_max_reconnect_attempts:
                    time.sleep(self.ws_reconnect_delay)
                    self.reconnect_websocket()
                    return
        
        self.ws_reconnect_count = 0  # Reset on success
        logger.info("All symbols subscribed successfully")

    def reconnect_websocket(self):
        """Reconnect WebSocket with exponential backoff"""
        logger.warning(f"Reconnecting WebSocket (attempt {self.ws_reconnect_count + 1})")
        
        try:
            if self.ws:
                self.ws.exit()
            
            # Exponential backoff
            delay = min(self.ws_reconnect_delay * (2 ** self.ws_reconnect_count), 60)
            time.sleep(delay)
            
            # Resubscribe
            self.subscribe_symbols(list(self.active_symbols))
            
        except Exception as e:
            logger.error(f"Reconnection failed: {e}")

    # ==================== MONITORING ====================
    
    async def monitor_performance(self):
        """Monitor and log performance metrics"""
        while True:
            await asyncio.sleep(30)
            
            try:
                if self.stats['messages'] > 0:
                    # Calculate rates
                    runtime = (datetime.now() - self.start_time).total_seconds()
                    avg_msg_rate = self.stats['messages'] / runtime if runtime > 0 else 0
                    
                    # Get Redis stats
                    db_size = self.redis_client.dbsize()
                    info = self.redis_client.info('memory')
                    mem_mb = info.get('used_memory', 0) / 1024 / 1024
                    
                    # Get queue size
                    with self.batch_lock:
                        queue_size = len(self.batch_queue)
                    
                    logger.info(
                        f"\n{'='*50}\n"
                        f"PERFORMANCE METRICS\n"
                        f"{'='*50}\n"
                        f"Messages:     {self.stats['messages']:,}\n"
                        f"Current Rate: {self.stats['msg_per_sec']:.0f} msg/s\n"
                        f"Average Rate: {avg_msg_rate:.0f} msg/s\n"
                        f"Batches:      {self.stats['batches']:,}\n"
                        f"Queue Size:   {queue_size}\n"
                        f"Errors:       {self.stats['errors']:,}\n"
                        f"Redis Keys:   {db_size:,}\n"
                        f"Redis Memory: {mem_mb:.2f} MB\n"
                        f"Uptime:       {runtime/60:.1f} minutes\n"
                        f"{'='*50}"
                    )
                    
                    # Check for issues
                    if queue_size > 5000:
                        logger.warning(f"Queue backlog detected: {queue_size} items")
                    
                    if self.stats['msg_per_sec'] < 100 and self.stats['messages'] > 10000:
                        logger.warning(f"Low message rate: {self.stats['msg_per_sec']:.0f}/s")
                        
            except Exception as e:
                logger.error(f"Monitoring error: {e}")

    # ==================== MAIN METHODS ====================
    
    async def track(self):
        """Track options with optimizations"""
        logger.info("="*60)
        logger.info("OPTIMIZED REAL-TIME TRACKING MODE")
        logger.info("="*60)
        
        self.start_time = datetime.now()
        
        # Initialize Redis with connection pooling
        if not self.init_redis():
            return
        
        # Clear database for fresh start
        self.clear_database()
        
        # Get symbols
        symbols = self.get_symbols()
        if not symbols:
            logger.error("No symbols to track")
            return
        
        logger.info(f"Loaded {len(symbols)} symbols")
        
        # Start performance monitor
        asyncio.create_task(self.monitor_performance())
        
        # Subscribe to WebSocket with optimizations
        self.subscribe_symbols(symbols)
        
        logger.info("Optimized tracking started. Press Ctrl+C to stop.\n")
        
        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
                
                # Check WebSocket health
                if self.ws and not self.ws.is_connected():
                    logger.warning("WebSocket disconnected, attempting reconnect...")
                    self.reconnect_websocket()
                    
        except KeyboardInterrupt:
            logger.info("Shutdown requested")

    def cleanup(self):
        """Clean shutdown"""
        logger.info("Shutting down...")
        
        # Process remaining batch
        with self.batch_lock:
            remaining = len(self.batch_queue)
            if remaining > 0:
                logger.info(f"Processing {remaining} remaining items...")
        
        if self.redis_client:
            try:
                runtime = (datetime.now() - self.start_time).total_seconds()
                avg_rate = self.stats['messages'] / runtime if runtime > 0 else 0
                
                self.redis_client.hset("stats", "shutdown_time", str(time.time()))
                self.redis_client.hset("stats", "total_messages", str(self.stats['messages']))
                self.redis_client.hset("stats", "avg_msg_rate", str(avg_rate))
                
                logger.info(
                    f"\nFinal Statistics:\n"
                    f"  Total Messages: {self.stats['messages']:,}\n"
                    f"  Total Batches:  {self.stats['batches']:,}\n"
                    f"  Total Errors:   {self.stats['errors']:,}\n"
                    f"  Average Rate:   {avg_rate:.0f} msg/s\n"
                    f"  Runtime:        {runtime/60:.1f} minutes"
                )
            except:
                pass
        
        if self.ws:
            self.ws.exit()
            logger.info("WebSocket closed")
        
        logger.info("Shutdown complete")


def main():
    """Main entry point"""
    
    # Check for Redis password in environment
    redis_password = os.getenv('REDIS_PASSWORD')
    
    # Parse command-line arguments
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        
        if mode in ['--help', '-h']:
            print("Optimized Bybit Options Tracker")
            print("\nUsage: python bybit_options_optimized.py [mode]")
            print("\nModes:")
            print("  fetch    - Only fetch symbols and save to cache")
            print("  track    - Track options in real-time (default)")
            print("  refresh  - Force refresh symbols then track")
            print("\nOptimizations:")
            print("  • Redis connection pooling")
            print("  • Batch processing (200 items)")
            print("  • Optimized WebSocket settings")
            print("  • Memory efficient data structures")
            print("  • Performance monitoring")
            return
        
        tracker = OptimizedOptionsTracker(redis_password=redis_password)
        
        if mode == 'fetch':
            symbols = tracker.get_symbols(force_refresh=True)
            if symbols:
                print(f"✅ Fetched {len(symbols)} symbols")
                
        elif mode == 'refresh':
            logger.info("Refreshing symbols...")
            tracker.get_symbols(force_refresh=True)
            try:
                asyncio.run(tracker.track())
            except KeyboardInterrupt:
                tracker.cleanup()
                
        elif mode == 'track':
            try:
                asyncio.run(tracker.track())
            except KeyboardInterrupt:
                tracker.cleanup()
        else:
            print(f"Unknown mode: {mode}")
    else:
        # Default: track
        tracker = OptimizedOptionsTracker(redis_password=redis_password)
        try:
            asyncio.run(tracker.track())
        except KeyboardInterrupt:
            tracker.cleanup()


if __name__ == "__main__":
    main()