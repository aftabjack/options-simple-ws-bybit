"""
Simple and efficient data reader for options data
Optimized for fast access and filtering
"""

import redis
import json
import time
from datetime import datetime
from typing import List, Dict, Optional, Any


class OptionsDataReader:
    def __init__(self, redis_host="localhost", redis_port=6379, redis_db=0, redis_password=None):
        """Initialize with Redis connection pooling"""
        self.pool = redis.ConnectionPool(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            max_connections=10,
            socket_keepalive=True,
            decode_responses=True
        )
        self.redis_client = redis.Redis(connection_pool=self.pool)
        
    def is_connected(self) -> bool:
        """Check Redis connection"""
        try:
            self.redis_client.ping()
            return True
        except:
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get system statistics"""
        try:
            stats = self.redis_client.hgetall("stats")
            
            # Get database info
            db_size = self.redis_client.dbsize()
            info = self.redis_client.info('memory')
            mem_mb = info.get('used_memory', 0) / 1024 / 1024
            
            return {
                'messages': int(stats.get('messages', 0)),
                'batches': int(stats.get('batches', 0)),
                'last_update': float(stats.get('last_update', 0)),
                'last_update_str': datetime.fromtimestamp(float(stats.get('last_update', 0))).strftime('%Y-%m-%d %H:%M:%S'),
                'db_keys': db_size,
                'memory_mb': round(mem_mb, 2),
                'connected': True
            }
        except Exception as e:
            return {'error': str(e), 'connected': False}
    
    def get_option(self, symbol: str) -> Optional[Dict]:
        """Get single option data"""
        try:
            data = self.redis_client.hgetall(f"option:{symbol}")
            if data:
                # Expand abbreviated keys
                return {
                    'symbol': symbol,
                    'timestamp': int(data.get('ts', 0)),
                    'bid_iv': float(data.get('biv', 0)),
                    'ask_iv': float(data.get('aiv', 0)),
                    'last_price': float(data.get('lp', 0)),
                    'mark_price': float(data.get('mp', 0)),
                    'index_price': float(data.get('ip', 0)),
                    'mark_iv': float(data.get('miv', 0)),
                    'underlying_price': float(data.get('up', 0)),
                    'open_interest': float(data.get('oi', 0)),
                    'delta': float(data.get('d', 0)),
                    'gamma': float(data.get('g', 0)),
                    'vega': float(data.get('v', 0)),
                    'theta': float(data.get('t', 0)),
                    'volume_24h': float(data.get('v24', 0)),
                    'turnover_24h': float(data.get('t24', 0))
                }
            return None
        except Exception as e:
            print(f"Error getting {symbol}: {e}")
            return None
    
    def get_all_options(self, asset: Optional[str] = None) -> List[Dict]:
        """Get all options, optionally filtered by asset"""
        options = []
        
        try:
            # Get all option keys
            pattern = f"option:{asset}-*" if asset else "option:*"
            keys = self.redis_client.keys(pattern)
            
            # Use pipeline for efficiency
            pipe = self.redis_client.pipeline()
            for key in keys:
                pipe.hgetall(key)
            
            results = pipe.execute()
            
            for key, data in zip(keys, results):
                if data:
                    symbol = key.replace("option:", "")
                    option = {
                        'symbol': symbol,
                        'timestamp': int(data.get('ts', 0)),
                        'bid_iv': float(data.get('biv', 0)) if data.get('biv') else 0,
                        'ask_iv': float(data.get('aiv', 0)) if data.get('aiv') else 0,
                        'last_price': float(data.get('lp', 0)) if data.get('lp') else 0,
                        'mark_price': float(data.get('mp', 0)) if data.get('mp') else 0,
                        'mark_iv': float(data.get('miv', 0)) if data.get('miv') else 0,
                        'open_interest': float(data.get('oi', 0)) if data.get('oi') else 0,
                        'volume_24h': float(data.get('v24', 0)) if data.get('v24') else 0,
                        'turnover_24h': float(data.get('t24', 0)) if data.get('t24') else 0
                    }
                    options.append(option)
            
            return options
            
        except Exception as e:
            print(f"Error getting options: {e}")
            return []
    
    def get_high_volume_options(self, min_volume: float = 100000) -> List[Dict]:
        """Get options with high trading volume"""
        all_options = self.get_all_options()
        return [opt for opt in all_options if opt['volume_24h'] >= min_volume]
    
    def get_high_iv_options(self, min_iv: float = 1.0) -> List[Dict]:
        """Get options with high implied volatility"""
        all_options = self.get_all_options()
        return [opt for opt in all_options if opt['mark_iv'] >= min_iv]
    
    def get_expiry_options(self, expiry_date: str) -> List[Dict]:
        """Get options for specific expiry date (format: YYMMDD)"""
        pattern = f"option:*-{expiry_date}-*"
        keys = self.redis_client.keys(pattern)
        
        options = []
        pipe = self.redis_client.pipeline()
        for key in keys:
            pipe.hgetall(key)
        
        results = pipe.execute()
        
        for key, data in zip(keys, results):
            if data:
                symbol = key.replace("option:", "")
                option = {
                    'symbol': symbol,
                    'last_price': float(data.get('lp', 0)) if data.get('lp') else 0,
                    'mark_iv': float(data.get('miv', 0)) if data.get('miv') else 0,
                    'open_interest': float(data.get('oi', 0)) if data.get('oi') else 0,
                    'volume_24h': float(data.get('v24', 0)) if data.get('v24') else 0
                }
                options.append(option)
        
        return options
    
    def get_summary(self) -> Dict:
        """Get summary of all data"""
        try:
            # Get all keys efficiently
            btc_count = len(self.redis_client.keys("option:BTC-*"))
            eth_count = len(self.redis_client.keys("option:ETH-*"))
            sol_count = len(self.redis_client.keys("option:SOL-*"))
            
            stats = self.get_stats()
            
            return {
                'total_symbols': btc_count + eth_count + sol_count,
                'btc_options': btc_count,
                'eth_options': eth_count,
                'sol_options': sol_count,
                'total_messages': stats.get('messages', 0),
                'last_update': stats.get('last_update_str', 'Unknown'),
                'memory_usage_mb': stats.get('memory_mb', 0)
            }
        except Exception as e:
            return {'error': str(e)}
    
    def export_to_json(self, filename: str, asset: Optional[str] = None):
        """Export data to JSON file"""
        options = self.get_all_options(asset)
        
        with open(filename, 'w') as f:
            json.dump({
                'exported_at': datetime.now().isoformat(),
                'count': len(options),
                'asset': asset or 'all',
                'data': options
            }, f, indent=2)
        
        print(f"Exported {len(options)} options to {filename}")
    
    def export_to_csv(self, filename: str, asset: Optional[str] = None):
        """Export data to CSV file"""
        import csv
        
        options = self.get_all_options(asset)
        
        if not options:
            print("No data to export")
            return
        
        with open(filename, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=options[0].keys())
            writer.writeheader()
            writer.writerows(options)
        
        print(f"Exported {len(options)} options to {filename}")


def main():
    """Example usage"""
    reader = OptionsDataReader()
    
    if not reader.is_connected():
        print("❌ Cannot connect to Redis")
        return
    
    print("✅ Connected to Redis\n")
    
    # Get summary
    summary = reader.get_summary()
    print("SUMMARY")
    print("="*50)
    for key, value in summary.items():
        print(f"{key:20}: {value}")
    
    print("\n" + "="*50)
    
    # Get high volume options
    high_volume = reader.get_high_volume_options(min_volume=50000)
    print(f"\nHigh Volume Options (>50k): {len(high_volume)}")
    for opt in high_volume[:5]:
        print(f"  {opt['symbol']:30} Vol: {opt['volume_24h']:,.0f}")
    
    # Get high IV options
    high_iv = reader.get_high_iv_options(min_iv=0.8)
    print(f"\nHigh IV Options (>0.8): {len(high_iv)}")
    for opt in high_iv[:5]:
        print(f"  {opt['symbol']:30} IV: {opt['mark_iv']:.2f}")
    
    # Export examples
    # reader.export_to_json("btc_options.json", "BTC")
    # reader.export_to_csv("all_options.csv")


if __name__ == "__main__":
    main()