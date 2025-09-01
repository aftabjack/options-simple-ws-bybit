"""
Unified Bybit Options Tracker - Symbol Fetching + Real-time Tracking
"""

import asyncio
import json
import redis
import requests
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from pybit.unified_trading import WebSocket


class UnifiedOptionsTracker:
    def __init__(self, cache_file="symbols_cache.json", redis_host="localhost", redis_port=6379, redis_db=0):
        self.cache_file = cache_file
        self.cache_duration_hours = 24
        self.known_option_assets = ['BTC', 'ETH', 'SOL']
        self.api_url = "https://api.bybit.com/v5/market/instruments-info"

        # Redis settings
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self.redis_client = None
        self.ws = None

        self.stats = {
            'messages': 0,
            'errors': 0,
            'last_update': None
        }

    # ==================== SYMBOL FETCHING METHODS ====================

    def load_cache(self):
        """Load symbols from cache if valid"""
        cache_path = Path(self.cache_file)

        if not cache_path.exists():
            print("No cache file found")
            return None

        try:
            with open(cache_path, 'r') as f:
                cache_data = json.load(f)

            # Check if cache is expired
            cached_time = datetime.fromisoformat(cache_data['updated_at'])
            expires_at = datetime.fromisoformat(cache_data['expires_at'])
            age_hours = (datetime.now() - cached_time).total_seconds() / 3600

            if datetime.now() > expires_at:
                print(f"Cache expired (age: {age_hours:.1f} hours)")
                return None

            print(f"Loaded {cache_data['count']} symbols from cache")
            print(f"Cache age: {age_hours:.1f} hours")
            print(f"Valid until: {expires_at.strftime('%Y-%m-%d %H:%M:%S')}")

            return cache_data['symbols']

        except Exception as e:
            print(f"Error reading cache: {e}")
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

        print(f"Saved {len(symbols)} symbols to cache")
        print(f"Cache will expire at: {cache_data['expires_at']}")

    def fetch_from_api(self):
        """Fetch symbols from Bybit API"""
        print("Fetching fresh symbols from API...")

        all_tickers = []

        for coin in self.known_option_assets:
            cursor = None
            coin_count = 0

            while True:
                params = {"category": "option", "baseCoin": coin, "limit": 1000}
                if cursor:
                    params["cursor"] = cursor

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

                except Exception as e:
                    print(f"  Error fetching {coin}: {e}")
                    break

            if coin_count > 0:
                print(f"  {coin}: {coin_count} options")

        print(f"Total fetched: {len(all_tickers)} symbols")
        return all_tickers

    def get_symbols(self, force_refresh=False):
        """Get symbols from cache or API"""

        # Force refresh if requested
        if force_refresh:
            print("Force refresh requested")
            symbols = self.fetch_from_api()
            if symbols:
                self.save_cache(symbols)
            return symbols

        # Try cache first
        symbols = self.load_cache()
        if symbols:
            return symbols

        # Cache miss or expired, fetch fresh
        symbols = self.fetch_from_api()
        if symbols:
            self.save_cache(symbols)

        return symbols

    # ==================== REDIS & TRACKING METHODS ====================

    def init_redis(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True
            )
            self.redis_client.ping()
            print("Redis connection successful")
            return True
        except Exception as e:
            print(f"Redis connection failed: {e}")
            print("Make sure Redis is running: redis-server")
            return False

    def clear_database(self):
        """Clear all Redis data on startup"""
        try:
            if self.redis_client:
                self.redis_client.flushdb()
                print("Redis database cleared for fresh start")
        except Exception as e:
            print(f"Error clearing Redis: {e}")

    def handle_message(self, message):
        """Handle WebSocket messages"""
        try:
            self.stats['messages'] += 1

            data = message.get("data")
            if not data:
                return

            symbol = data.get('symbol')
            if not symbol:
                return

            # Prepare data for Redis
            record = {
                'timestamp': time.time(),
                'bid_iv': self._to_float(data.get('bidIv')),
                'ask_iv': self._to_float(data.get('askIv')),
                'last_price': self._to_float(data.get('lastPrice')),
                'mark_price': self._to_float(data.get('markPrice')),
                'index_price': self._to_float(data.get('indexPrice')),
                'mark_iv': self._to_float(data.get('markPriceIv')),
                'underlying_price': self._to_float(data.get('underlyingPrice')),
                'open_interest': self._to_float(data.get('openInterest')),
                'delta': self._to_float(data.get('delta')),
                'gamma': self._to_float(data.get('gamma')),
                'vega': self._to_float(data.get('vega')),
                'theta': self._to_float(data.get('theta')),
                'volume_24h': self._to_float(data.get('volume24h')),
                'turnover_24h': self._to_float(data.get('turnover24h')),
            }

            # Store in Redis
            hash_key = f"option:{symbol}"
            self.redis_client.hset(hash_key, mapping={
                k: str(v) if v is not None else ""
                for k, v in record.items()
            })
            self.redis_client.expire(hash_key, 86400)

            # Update stats
            self.redis_client.hincrby("stats", "messages", 1)
            self.redis_client.hset("stats", "last_update", str(time.time()))

            self.stats['last_update'] = datetime.now()

            # Show progress
            if self.stats['messages'] % 1000 == 0:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Processed: {self.stats['messages']} | "
                      f"Errors: {self.stats['errors']}")

        except Exception as e:
            self.stats['errors'] += 1
            if self.stats['errors'] % 100 == 0:
                print(f"[ERROR] {e}")

    def _to_float(self, value):
        """Safely convert to float"""
        try:
            return float(value) if value else None
        except:
            return None

    def subscribe_symbols(self, symbols):
        """Subscribe to symbols via WebSocket"""
        self.ws = WebSocket(testnet=False, channel_type="option")

        # Subscribe in chunks
        chunk_size = 50
        chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]

        print(f"\nSubscribing to {len(symbols)} symbols in {len(chunks)} batches...")

        for i, chunk in enumerate(chunks):
            try:
                self.ws.ticker_stream(
                    symbol=chunk,
                    callback=self.handle_message
                )
                print(f"  Batch {i + 1}/{len(chunks)}: {len(chunk)} symbols subscribed")
                time.sleep(0.2)

            except Exception as e:
                print(f"  Error subscribing batch {i + 1}: {e}")

        print(f"Successfully subscribed to symbols\n")

    # ==================== MAIN METHODS ====================

    def fetch_only(self):
        """Just fetch and save symbols"""
        print("=" * 60)
        print("SYMBOL FETCH MODE")
        print("=" * 60)

        symbols = self.get_symbols(force_refresh=True)

        if symbols:
            print(f"\n✅ Successfully fetched {len(symbols)} symbols")

            # Show breakdown
            btc_count = len([s for s in symbols if s.startswith('BTC-')])
            eth_count = len([s for s in symbols if s.startswith('ETH-')])
            sol_count = len([s for s in symbols if s.startswith('SOL-')])

            print(f"\nBreakdown:")
            print(f"  BTC: {btc_count}")
            print(f"  ETH: {eth_count}")
            print(f"  SOL: {sol_count}")

            print(f"\nFirst 5 symbols: {symbols[:5]}")
        else:
            print("Failed to fetch symbols")

        print("=" * 60)

    async def track(self):
        """Track options in real-time"""
        print("=" * 60)
        print("REAL-TIME TRACKING MODE")
        print("=" * 60)

        # Initialize Redis
        if not self.init_redis():
            return

        # Clear database for fresh start
        self.clear_database()

        # Get symbols (from cache or API)
        symbols = self.get_symbols()
        if not symbols:
            print("No symbols to track. Exiting.")
            return

        print(f"\nLoaded {len(symbols)} symbols")

        # Subscribe to WebSocket
        self.subscribe_symbols(symbols)

        print("Real-time tracking started. Press Ctrl+C to stop.\n")

        # Keep running and show stats
        while True:
            await asyncio.sleep(30)

            if self.stats['messages'] > 0:
                print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Stats Update:")
                print(f"  Total messages: {self.stats['messages']:,}")
                print(f"  Total errors: {self.stats['errors']:,}")

                try:
                    db_keys = self.redis_client.dbsize()
                    info = self.redis_client.info('memory')
                    mem_mb = info.get('used_memory', 0) / 1024 / 1024

                    print(f"  Redis keys: {db_keys:,}")
                    print(f"  Redis memory: {mem_mb:.2f} MB")
                except:
                    pass

    def cleanup(self):
        """Clean shutdown"""
        print("\nShutting down...")

        if self.redis_client:
            try:
                self.redis_client.hset("stats", "shutdown_time", str(time.time()))
                print(f"Final stats: {self.stats['messages']} messages processed")
            except:
                pass

        if self.ws:
            self.ws.exit()
            print("WebSocket closed")

        print("Shutdown complete")


def main():
    """Main entry point with command-line options"""

    # Parse command-line arguments
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()

        if mode in ['--help', '-h']:
            print("Usage: python options_tracker_unified.py [mode]")
            print("\nModes:")
            print("  fetch    - Only fetch symbols and save to cache")
            print("  track    - Track options in real-time (default)")
            print("  refresh  - Force refresh symbols then track")
            print("\nExamples:")
            print("  python options_tracker_unified.py fetch")
            print("  python options_tracker_unified.py track")
            print("  python options_tracker_unified.py refresh")
            return

        tracker = UnifiedOptionsTracker()

        if mode == 'fetch':
            # Just fetch symbols
            tracker.fetch_only()

        elif mode == 'refresh':
            # Force refresh then track
            print("Refreshing symbols first...")
            tracker.get_symbols(force_refresh=True)
            print("\nStarting tracker...")
            try:
                asyncio.run(tracker.track())
            except KeyboardInterrupt:
                tracker.cleanup()

        elif mode == 'track':
            # Normal tracking
            try:
                asyncio.run(tracker.track())
            except KeyboardInterrupt:
                tracker.cleanup()
        else:
            print(f"Unknown mode: {mode}")
            print("Use --help for usage information")
    else:
        # Default mode: track
        tracker = UnifiedOptionsTracker()
        try:
            asyncio.run(tracker.track())
        except KeyboardInterrupt:
            tracker.cleanup()


if __name__ == "__main__":
    main()