import logging
from alpaca.trading.requests import (
    MarketOrderRequest,
    TakeProfitRequest,
    StopLossRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
from alpaca.data.requests import StockLatestQuoteRequest
import alpaca_client
import config
from analyzer import TradeSignal
import trade_tracker

logger = logging.getLogger(__name__)


def is_market_open() -> bool:
    try:
        return alpaca_client.trading().get_clock().is_open
    except Exception as e:
        logger.warning(f"Could not check market clock: {e}")
        return False


def get_position_count() -> int:
    try:
        return len(alpaca_client.trading().get_all_positions())
    except Exception:
        return config.MAX_POSITIONS  # fail safe


def get_buying_power() -> float:
    return float(alpaca_client.trading().get_account().buying_power)


def get_ask_price(ticker: str) -> float:
    req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
    quotes = alpaca_client.data().get_stock_latest_quote(req)
    price = float(quotes[ticker].ask_price or quotes[ticker].bid_price or 0)
    if price <= 0:
        raise ValueError(f"No valid price for {ticker}")
    return price


def execute_trade(signal: TradeSignal) -> bool:
    """Place a bracket order for each HIGH-confidence ticker. Returns True if any order placed."""
    if not signal.market_relevant or signal.signal == "HOLD":
        return False
    if signal.confidence != "HIGH":
        logger.info(f"Skipping {signal.tickers} — confidence {signal.confidence} (need HIGH)")
        return False
    if not signal.tickers:
        return False
    if not is_market_open():
        logger.info(f"Market closed — skipping trade for {signal.tickers}")
        return False
    if get_position_count() >= config.MAX_POSITIONS:
        logger.warning(f"At max positions ({config.MAX_POSITIONS}), skipping")
        return False

    buying_power = get_buying_power()
    budget = buying_power * config.POSITION_SIZE_PCT
    side = OrderSide.BUY if signal.signal == "BUY" else OrderSide.SELL
    placed = False

    for ticker in signal.tickers[:2]:
        try:
            price = get_ask_price(ticker)
            qty = max(1, int(budget / price))

            if side == OrderSide.BUY:
                tp_price = round(price * (1 + config.TAKE_PROFIT_PCT), 2)
                sl_price = round(price * (1 - config.STOP_LOSS_PCT), 2)
            else:
                tp_price = round(price * (1 - config.TAKE_PROFIT_PCT), 2)
                sl_price = round(price * (1 + config.STOP_LOSS_PCT), 2)

            order_req = MarketOrderRequest(
                symbol=ticker,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.DAY,
                order_class=OrderClass.BRACKET,
                take_profit=TakeProfitRequest(limit_price=tp_price),
                stop_loss=StopLossRequest(stop_price=sl_price),
            )
            order = alpaca_client.trading().submit_order(order_req)

            logger.info(
                f"ORDER PLACED | {side.value.upper()} {qty}x {ticker} @ ~${price:.2f} "
                f"| TP: ${tp_price} | SL: ${sl_price} | ID: {order.id}"
            )

            trade_tracker.record_trade(
                post_id=signal.post_id,
                ticker=ticker,
                side=side.value,
                qty=qty,
                entry_price=price,
                alpaca_order_id=str(order.id),
                tp_price=tp_price,
                sl_price=sl_price,
                signal=signal.signal,
                confidence=signal.confidence,
                post_preview=signal.reasoning,
            )
            placed = True

        except Exception as e:
            logger.error(f"Trade failed for {ticker}: {e}")

    return placed
