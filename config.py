import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() == "true"

TRUTH_SOCIAL_BASE = "https://truthsocial.com/api/v1"
TRUMP_ACCOUNT_HANDLE = "realDonaldTrump"
POLL_INTERVAL_SECONDS = 120  # 2 minutes

POSITION_SIZE_PCT = 0.05   # 5% of buying power per trade
STOP_LOSS_PCT = 0.05        # 5% stop loss
TAKE_PROFIT_PCT = 0.15      # 15% take profit
MAX_POSITIONS = 3           # max concurrent positions from this pipeline

CLAUDE_MODEL = "claude-sonnet-4-6"
