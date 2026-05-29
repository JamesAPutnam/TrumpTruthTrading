import csv
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
import alpaca_client

logger = logging.getLogger(__name__)

TRADES_FILE = Path("data/trades.csv")

FIELDS = [
    "trade_id", "post_id", "ticker", "side", "qty",
    "entry_price", "entry_time", "alpaca_order_id",
    "tp_price", "sl_price",
    "status",         # open | closed
    "exit_price", "exit_time", "pnl_pct",
    "outcome",        # TP_HIT | SL_HIT | UNKNOWN
    "signal", "confidence", "post_preview",
]


def _read() -> list[dict]:
    if not TRADES_FILE.exists():
        return []
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(trades: list[dict]):
    TRADES_FILE.parent.mkdir(exist_ok=True)
    with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(trades)


def record_trade(
    post_id: str,
    ticker: str,
    side: str,
    qty: int,
    entry_price: float,
    alpaca_order_id: str,
    tp_price: float,
    sl_price: float,
    signal: str,
    confidence: str,
    post_preview: str,
):
    trades = _read()
    trades.append({
        "trade_id": str(uuid.uuid4())[:8],
        "post_id": post_id,
        "ticker": ticker,
        "side": side,
        "qty": qty,
        "entry_price": round(entry_price, 4),
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "alpaca_order_id": alpaca_order_id,
        "tp_price": round(tp_price, 4),
        "sl_price": round(sl_price, 4),
        "status": "open",
        "exit_price": "",
        "exit_time": "",
        "pnl_pct": "",
        "outcome": "",
        "signal": signal,
        "confidence": confidence,
        "post_preview": post_preview[:200],
    })
    _write(trades)
    logger.info(f"Recorded trade: {side.upper()} {qty}x {ticker}")


def check_and_close_trades():
    """Query Alpaca for bracket order outcomes and update open trades."""
    trades = _read()
    open_trades = [t for t in trades if t["status"] == "open"]
    if not open_trades:
        return

    client = alpaca_client.trading()
    updated = False

    for trade in open_trades:
        try:
            order = client.get_order_by_id(trade["alpaca_order_id"])
            filled_leg = None
            for leg in order.legs or []:
                if leg.status.value == "filled":
                    filled_leg = leg
                    break

            if not filled_leg:
                continue  # still open

            exit_price = float(filled_leg.filled_avg_price)
            entry_price = float(trade["entry_price"])
            is_buy = trade["side"].lower() == "buy"
            pnl_pct = (
                (exit_price - entry_price) / entry_price * 100
                if is_buy
                else (entry_price - exit_price) / entry_price * 100
            )
            outcome = "TP_HIT" if filled_leg.order_type.value == "limit" else "SL_HIT"
            exit_time = (
                filled_leg.filled_at.isoformat()
                if filled_leg.filled_at
                else datetime.now(timezone.utc).isoformat()
            )

            trade.update({
                "status": "closed",
                "exit_price": round(exit_price, 4),
                "exit_time": exit_time,
                "pnl_pct": round(pnl_pct, 2),
                "outcome": outcome,
            })
            updated = True
            logger.info(
                f"Trade closed: {trade['ticker']} {outcome} | "
                f"PnL: {pnl_pct:+.2f}%"
            )

        except Exception as e:
            logger.warning(f"Could not check trade {trade['trade_id']} ({trade['ticker']}): {e}")

    if updated:
        _write(trades)


def build_performance_context() -> str:
    """Return a formatted performance summary to inject into the LLM prompt."""
    trades = _read()
    closed = [t for t in trades if t["status"] == "closed" and t["pnl_pct"] != ""]

    if len(closed) < 3:
        return ""  # not enough history to be meaningful

    pnl_values = [float(t["pnl_pct"]) for t in closed]
    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p <= 0]

    win_rate = len(wins) / len(closed) * 100
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    # Performance split by signal direction
    buy_closed = [t for t in closed if t["signal"] == "BUY"]
    sell_closed = [t for t in closed if t["signal"] == "SELL"]

    def win_rate_str(subset: list[dict]) -> str:
        if not subset:
            return "n/a"
        wins_s = sum(1 for t in subset if float(t["pnl_pct"]) > 0)
        return f"{wins_s}/{len(subset)} ({wins_s/len(subset)*100:.0f}%)"

    # 5 most recent closed trades
    recent = closed[-5:]
    recent_parts = []
    for t in reversed(recent):
        p = float(t["pnl_pct"])
        recent_parts.append(
            f"{t['ticker']} {t['signal']} {p:+.1f}%{'✓' if p > 0 else '✗'}"
        )
    recent_str = " | ".join(recent_parts)

    lines = [
        "PAST TRADING PERFORMANCE (use to calibrate your confidence):",
        f"• {len(closed)} closed trades | Win rate: {win_rate:.0f}% | "
        f"Avg win: +{avg_win:.1f}% | Avg loss: {avg_loss:.1f}%",
        f"• BUY trades won: {win_rate_str(buy_closed)} | "
        f"SELL trades won: {win_rate_str(sell_closed)}",
        f"• Recent (newest first): {recent_str}",
    ]
    return "\n".join(lines)
