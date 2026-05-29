from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
import config

_trading: TradingClient | None = None
_data: StockHistoricalDataClient | None = None


def trading() -> TradingClient:
    global _trading
    if _trading is None:
        _trading = TradingClient(
            config.ALPACA_API_KEY,
            config.ALPACA_SECRET_KEY,
            paper=config.ALPACA_PAPER,
        )
    return _trading


def data() -> StockHistoricalDataClient:
    global _data
    if _data is None:
        _data = StockHistoricalDataClient(
            config.ALPACA_API_KEY, config.ALPACA_SECRET_KEY
        )
    return _data
