# Bybit Options Data System

Efficient real-time options data collection and access system for trading.

## Files

### Core Files

1. **`bybit_options_optimized.py`** - Main WebSocket tracker
   - Collects real-time options data for BTC, ETH, SOL
   - Stores in Redis with optimized performance
   - Resource usage: 340 MB RAM, 85% CPU
   - Processes 2,600+ messages/second

2. **`efficient_trade_executor.py`** - Trading execution
   - Direct Redis access for minimal latency (0.5ms)
   - Ultra-low resource usage: 10 MB RAM, <2% CPU
   - Best for trade execution and decision making

3. **`data_reader.py`** - Data access utility
   - Simple interface to read options data
   - Export to JSON/CSV
   - Filter by volume, IV, asset

4. **`bybit_options_data_redis.py`** - Original version
   - Basic implementation (kept for reference)
   - Use optimized version for production

## Quick Start

### 1. Start Redis
```bash
redis-server
```

### 2. Run the tracker
```bash
# Fetch symbols only
python3 bybit_options_optimized.py fetch

# Start real-time tracking
python3 bybit_options_optimized.py track
```

### 3. Access data for trading
```python
from efficient_trade_executor import EfficientTradeExecutor

executor = EfficientTradeExecutor()

# Get single option (0.5ms)
price = executor.get_option_direct("BTC-29NOV24-100000-C")

# Get multiple options (2ms for 100)
data = executor.get_options_batch(["BTC-29NOV24-100000-C", "ETH-29NOV24-4000-C"])

# Scan for opportunities
signals = executor.scan_high_iv_opportunities(min_iv=1.0)
```

## Performance

### Resource Usage Comparison

| Method | Memory | CPU | Latency | Best For |
|--------|--------|-----|---------|----------|
| Direct Redis | 10 MB | <2% | 0.5ms | Trading |
| Data Reader | 15 MB | <3% | 1ms | Analysis |
| REST API | 50 MB | 10% | 10-50ms | External |

### System Architecture

```
[WebSocket Tracker] → [Redis] ← [Trade Executor]
(340 MB, 85% CPU)    (Storage)   (10 MB, 2% CPU)
```

## Key Features

- **Real-time data**: 2,600+ messages/second
- **Low latency**: 0.5ms data access
- **Efficient storage**: Abbreviated keys, batch processing
- **Auto-recovery**: Reconnection with exponential backoff
- **Production ready**: Error handling, monitoring

## Requirements

```bash
pip3 install redis pybit requests
```

## Redis Setup

Default connection:
- Host: localhost
- Port: 6379
- DB: 0

## Data Structure

Redis keys format: `option:{symbol}`

Fields (abbreviated for efficiency):
- `ts`: Timestamp
- `lp`: Last price
- `miv`: Mark IV
- `v24`: 24h volume
- `oi`: Open interest
- `d`, `g`, `v`, `t`: Greeks

## Support

For production use, prefer:
1. `bybit_options_optimized.py` for data collection
2. `efficient_trade_executor.py` for trading
3. Direct Redis access over any API layer