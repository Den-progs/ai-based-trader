"""
config.py — all bot settings in one place. Change values here, not in other files.
"""

# Seconds between trading cycles. Lower = more aggressive.
LOOP_INTERVAL = 30

# -- Stocks -------------------------------------------------------------------
# Shares to buy or sell per single stock order
QTY_PER_TRADE = 3

# Max shares we'll hold for any one stock at once (aggressive scaling in)
MAX_POSITION_SHARES = 15

# -- Crypto -------------------------------------------------------------------
# Dollar amount to spend per crypto buy (avoids giant positions since 1 ETH != 1 AAPL)
CRYPTO_TRADE_DOLLARS = 300

# Max dollar value we'll hold in any single crypto at once
MAX_CRYPTO_POSITION_VALUE = 2000

# -- General ------------------------------------------------------------------
# Minimum Llama confidence to act
CONFIDENCE_THRESHOLD = 0.70

# Parallel Llama calls -- lets 50 stocks finish in ~20s instead of ~3 minutes
THREAD_WORKERS = 4

# Sell all stock positions this many minutes before market close
EOD_LIQUIDATE_MINUTES_BEFORE_CLOSE = 10

# Minimum seconds between two BUY orders for the same symbol
BUY_COOLDOWN_SECONDS = 600  # 10 minutes

# Auto-sell a position when unrealized profit hits this dollar amount
# Set to 0 to disable
TAKE_PROFIT_DOLLARS = 150
