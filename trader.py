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

ACTIONABLE = {"HIGH", "EXTREME"}


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
        return config.MAX_POSITIONS


def get_buying_power() -> float:
    return float(alpaca_client.trading().get_account().buying_power)


def get_ask_price(ticker: str) -> float:
    req = StockLatestQuoteRequest(symbol_or_symbols=ticker)
    quotes = alpaca_client.data().get_stock_latest_quote(req)
    price = float(quotes[ticker].ask_price or quotes[ticker].bid_price or 0)
    if price <= 0:
        raise ValueError(f"No valid price for {ticker}")
    return price


def _close_conflicting_positions(signal: TradeSignal):
    """Close any existing position that is the opposite direction of the new signal."""
    try:
        positions = {
            p.symbol: p.side.value
            for p in alpaca_client.trading().get_all_positions()
        }
    except Exception as e:
        logger.warning(f"Could not fetch positions for reversal check: {e}")
        return

    for ticker in signal.tickers:
        existing = positions.get(ticker)
        if not existing:
            continue
        is_reversal = (existing == "long" and signal.signal == "SELL") or \
                      (existing == "short" and signal.signal == "BUY")
        if is_reversal:
            try:
                alpaca_client.trading().close_position(ticker)
                logger.info(f"Closed existing {existing} position in {ticker} — reversal signal")
            except Exception as e:
                logger.warning(f"Could not close {ticker} for reversal: {e}")


def _place_bracket_order(ticker: str, side: OrderSide, price: float, budget: float) -> bool:
    """Place a bracket order. Returns True on success."""
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
    return str(order.id), qty, tp_price, sl_price


def execute_trade(signal: TradeSignal) -> bool:
    """Evaluate signal and act. Returns True if an order was placed."""
    if not signal.market_relevant or signal.signal == "HOLD":
        return False
    if signal.confidence not in ACTIONABLE:
        logger.info(f"Skipping {signal.tickers} — confidence {signal.confidence} (need HIGH or EXTREME)")
        return False
    if not signal.tickers:
        return False

    # Duplicate guard — never trade the same post twice
    if trade_tracker.already_traded(signal.post_id):
        logger.info(f"Post {signal.post_id} already traded or queued, skipping")
        return False

    # EXTREME signal outside market hours → queue for open
    if not is_market_open():
        if signal.confidence == "EXTREME":
            trade_tracker.add_pending_signal(
                post_id=signal.post_id,
                tickers=signal.tickers,
                signal=signal.signal,
                reasoning=signal.reasoning,
            )
        else:
            logger.info(f"Market closed — skipping {signal.tickers}")
        return False

    if get_position_count() >= config.MAX_POSITIONS:
        logger.warning(f"At max positions ({config.MAX_POSITIONS}), skipping")
        return False

    _close_conflicting_positions(signal)

    buying_power = get_buying_power()
    budget = buying_power * config.POSITION_SIZE_PCT
    side = OrderSide.BUY if signal.signal == "BUY" else OrderSide.SELL
    placed = False

    for ticker in signal.tickers[:2]:
        try:
            price = get_ask_price(ticker)
            order_id, qty, tp_price, sl_price = _place_bracket_order(ticker, side, price, budget)
            trade_tracker.record_trade(
                post_id=signal.post_id,
                ticker=ticker,
                side=side.value,
                qty=qty,
                entry_price=price,
                alpaca_order_id=order_id,
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
