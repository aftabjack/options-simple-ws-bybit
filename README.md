# Bybit Options WebSocket Tracker

Optimized real-time options data collection system for BTC, ETH, and SOL options on Bybit.

## Quick Start

### 1. Install Dependencies
```bash
pip3 install redis pybit requests
```

### 2. Start Redis
```bash
redis-server
```

### 3. Run the Tracker
```bash
# Start real-time tracking
python3 bybit_options_optimized.py track

# Or just fetch symbols
python3 bybit_options_optimized.py fetch
```

### 4. Access Data (for Trading)
```python
import redis

# Connect to Redis
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Get option data (0.5ms latency)
data = r.hmget("option:BTC-29NOV24-100000-C", "lp", "miv", "v24")
price = float(data[0]) if data[0] else 0
iv = float(data[1]) if data[1] else 0
volume = float(data[2]) if data[2] else 0
```

## Performance

- **Processing Speed**: 2,600+ messages/second
- **Memory Usage**: 340 MB
- **CPU Usage**: 85%
- **Data Access Latency**: 0.5ms
- **Symbols Tracked**: ~2,000 options

## Data Structure

Redis keys format: `option:{symbol}`

Fields (optimized with short keys):
- `ts`: Timestamp (integer)
- `lp`: Last Price
- `mp`: Mark Price
- `miv`: Mark IV
- `biv`: Bid IV
- `aiv`: Ask IV
- `v24`: 24h Volume
- `oi`: Open Interest
- `d`: Delta
- `g`: Gamma
- `v`: Vega
- `t`: Theta

## Trading Example

```python
import redis
import time

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def get_option_data(symbol):
    """Get option data with 0.5ms latency"""
    data = r.hmget(f"option:{symbol}", "lp", "miv", "v24", "oi")
    if not data[0]:
        return None
    
    return {
        'price': float(data[0]) if data[0] else 0,
        'iv': float(data[1]) if data[1] else 0,
        'volume': float(data[2]) if data[2] else 0,
        'oi': float(data[3]) if data[3] else 0
    }

def scan_opportunities():
    """Scan all options for trading opportunities"""
    high_iv_options = []
    
    # Get all option keys
    keys = r.keys("option:*")
    
    # Use pipeline for efficiency
    pipe = r.pipeline()
    for key in keys:
        pipe.hmget(key, "miv", "lp", "v24")
    
    results = pipe.execute()
    
    for key, data in zip(keys, results):
        if data[0]:  # Has data
            iv = float(data[0]) if data[0] else 0
            if iv > 1.0:  # High IV threshold
                symbol = key.replace("option:", "")
                high_iv_options.append({
                    'symbol': symbol,
                    'iv': iv,
                    'price': float(data[1]) if data[1] else 0,
                    'volume': float(data[2]) if data[2] else 0
                })
    
    return sorted(high_iv_options, key=lambda x: x['iv'], reverse=True)

# Trading loop example
def trading_loop():
    while True:
        # Check specific option
        data = get_option_data("BTC-29NOV24-100000-C")
        if data and data['iv'] > 1.5 and data['volume'] > 50000:
            print(f"SIGNAL: High IV {data['iv']:.2f} on BTC option")
        
        # Or scan all options
        opportunities = scan_opportunities()
        for opp in opportunities[:5]:  # Top 5
            print(f"{opp['symbol']}: IV={opp['iv']:.2f}, Vol={opp['volume']:.0f}")
        
        time.sleep(5)  # Check every 5 seconds
```

## Resource Usage Comparison

| Method | Memory | CPU | Latency | Use Case |
|--------|--------|-----|---------|----------|
| Direct Redis | 10 MB | <2% | 0.5ms | Trading execution |
| With Caching | 20 MB | <1% | 0.01ms | Repeated reads |
| REST API | 50+ MB | 10% | 10-50ms | External access |

## Architecture

```
[WebSocket Tracker] → [Redis] ← [Your Trading Script]
(340 MB, 85% CPU)    (Storage)   (10 MB, <2% CPU)
```

## Optimizations Applied

1. **Connection Pooling**: Reuse Redis connections
2. **Batch Processing**: Process 200 messages at once
3. **Abbreviated Keys**: Reduce memory by 35%
4. **WebSocket Tuning**: Ping interval 45s, timeout 15s
5. **Error Recovery**: Exponential backoff reconnection

## Command Line Options

```bash
# Fetch symbols only
python3 bybit_options_optimized.py fetch

# Start tracking (default)
python3 bybit_options_optimized.py track

# Force refresh symbols then track
python3 bybit_options_optimized.py refresh

# Show help
python3 bybit_options_optimized.py --help
```

## Files

- `bybit_options_optimized.py` - Main WebSocket tracker (required)
- `symbols_cache.json` - Symbol cache (auto-generated)
- `README.md` - This documentation

## Requirements

- Python 3.7+
- Redis server
- ~350 MB RAM
- Network connection to Bybit

## Troubleshooting

### Redis Connection Error
```bash
# Check if Redis is running
redis-cli ping
# Should return: PONG

# If not, start Redis
redis-server
```

### High CPU Usage
- Normal: 85% CPU for processing 2,600 msg/s
- Reduce by filtering symbols or increasing batch size

### WebSocket Timeout
- Already fixed with ping_interval=45, ping_timeout=15
- Check network connectivity to Bybit

## Production Tips

1. **Use local Redis** for lowest latency
2. **Run tracker as systemd service** for auto-restart
3. **Monitor with**: `redis-cli info stats`
4. **Set Redis max memory**: `redis-cli CONFIG SET maxmemory 1gb`

## Data Export Example

```python
import redis
import json
import csv

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def export_to_json(asset="BTC"):
    """Export options data to JSON"""
    keys = r.keys(f"option:{asset}-*")
    data = []
    
    pipe = r.pipeline()
    for key in keys:
        pipe.hgetall(key)
    
    results = pipe.execute()
    
    for key, values in zip(keys, results):
        if values:
            symbol = key.replace("option:", "")
            data.append({
                'symbol': symbol,
                'last_price': float(values.get('lp', 0) or 0),
                'mark_iv': float(values.get('miv', 0) or 0),
                'volume_24h': float(values.get('v24', 0) or 0),
                'open_interest': float(values.get('oi', 0) or 0)
            })
    
    with open(f'{asset}_options.json', 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"Exported {len(data)} {asset} options")

# Export BTC options
export_to_json("BTC")
```

## License

MIT

## Support

For issues or questions, check the repository:
https://github.com/aftabjack/options-simple-ws-bybit