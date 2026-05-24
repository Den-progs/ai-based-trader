"""
config.py — all bot settings in one place. Change values here, not in other files.
"""

# Seconds between trading cycles. Lower = more aggressive.
LOOP_INTERVAL = 5

# Shares to buy or sell per single order
QTY_PER_TRADE = 3

# Max shares we'll hold for any one stock at once (aggressive scaling in)
MAX_POSITION_SHARES = 15

# Minimum Llama confidence to act — 0.55 catches more signals than the old 0.70
CONFIDENCE_THRESHOLD = 0.55

# Parallel Llama calls — lets 50 stocks finish in ~20s instead of ~3 minutes
THREAD_WORKERS = 8

# Sell all stock positions this many minutes before market close
# Keeps us flat overnight on a day-trading strategy
EOD_LIQUIDATE_MINUTES_BEFORE_CLOSE = 10
