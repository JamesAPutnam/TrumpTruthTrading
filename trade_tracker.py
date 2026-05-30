import csv
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
import alpaca_client

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
TRADES_FILE = DATA_DIR / "trades.csv"
PENDING_FILE = DATA_DIR / "pending_signals.json"

PENDING_TTL_HOURS = 48  # discard unexecuted EXTREME signals after this long

FIELDS = [
    "trade_id", "post_id", "ticker", "side", "qty",
    "entry_price", "entry_time", "alpaca_order_id",
    "tp_price", "sl_price",
    "status",         # open | closed
    "exit_price", "exit_time", "pnl_pct",
    "outcome",        # TP_HIT | SL_HIT | UNKNOWN
    "signal", "confidence", "post_preview",
]


# ── trades.csv helpers ────────────────────────────────────────────────────────

def _read() -> list[dict]:
    if not TRADES_FILE.exists():
        return []
    with open(TRADES_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(trades: list[dict]):
    DATA_DIR.mkdir(exist_ok=True)
    with open(TRADES_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(trades)


def already_traded(post_id: str) -> bool:
    """Return True if we already placed (or queued) a trade for this post."""
    if any(t["post_id"] == post_id for t in _read()):
        return True
    return any(p["post_id"] == post_id for p in get_pending_signals())


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
    """Query Alpaca bracket order legs and update any resolved trades."""
    trades = _read()
    open_trades = [t for t in trades if t["status"] == "open"]
    if not open_trades:
        return

    client = alpaca_client.trading()
    updated = False

    for trade in open_trades:
        try:
            order = client.get_order_by_id(trade["alpaca_order_id"])
            filled_leg = next(
                (leg for leg in (order.legs or []) if leg.status.value == "filled"),
                None,
            )
            if not filled_leg:
                continue

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
            logger.info(f"Trade closed: {trade['ticker']} {outcome} | PnL: {pnl_pct:+.2f}%")

        except Exception as e:
            logger.warning(f"Could not check trade {trade['trade_id']} ({trade['ticker']}): {e}")

    if updated:
        _write(trades)


# ── pending_signals.json helpers ──────────────────────────────────────────────

def _read_pending() -> list[dict]:
    if not PENDING_FILE.exists():
        return []
    try:
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _write_pending(pending: list[dict]):
    DATA_DIR.mkdir(exist_ok=True)
    PENDING_FILE.write_text(json.dumps(pending, indent=2), encoding="utf-8")


def get_pending_signals() -> list[dict]:
    return _read_pending()


def add_pending_signal(post_id: str, tickers: list[str], signal: str, reasoning: str):
    pending = _read_pending()
    if any(p["post_id"] == post_id for p in pending):
        return  # already queued
    pending.append({
        "post_id": post_id,
        "tickers": tickers,
        "signal": signal,
        "reasoning": reasoning,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    _write_pending(pending)
    logger.info(f"Queued EXTREME signal for market open: {tickers}")


def remove_pending_signal(post_id: str):
    pending = [p for p in _read_pending() if p["post_id"] != post_id]
    _write_pending(pending)


def purge_expired_pending():
    """Remove pending signals older than PENDING_TTL_HOURS."""
    now = datetime.now(timezone.utc)
    pending = _read_pending()
    fresh = []
    for p in pending:
        age_hours = (now - datetime.fromisoformat(p["created_at"])).total_seconds() / 3600
        if age_hours > PENDING_TTL_HOURS:
            logger.info(f"Expired pending signal for {p['tickers']} (>{PENDING_TTL_HOURS}h old)")
        else:
            fresh.append(p)
    if len(fresh) != len(pending):
        _write_pending(fresh)


# ── performance context ───────────────────────────────────────────────────────

def build_performance_context() -> str:
    trades = _read()
    closed = [t for t in trades if t["status"] == "closed" and t["pnl_pct"] != ""]

    if len(closed) < 3:
        return ""

    pnl_values = [float(t["pnl_pct"]) for t in closed]
    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p <= 0]
    win_rate = len(wins) / len(closed) * 100
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    buy_closed = [t for t in closed if t["signal"] == "BUY"]
    sell_closed = [t for t in closed if t["signal"] == "SELL"]

    def wr(subset):
        if not subset:
            return "n/a"
        w = sum(1 for t in subset if float(t["pnl_pct"]) > 0)
        return f"{w}/{len(subset)} ({w/len(subset)*100:.0f}%)"

    recent = closed[-5:]
    recent_str = " | ".join(
        f"{t['ticker']} {t['signal']} {float(t['pnl_pct']):+.1f}%{'✓' if float(t['pnl_pct']) > 0 else '✗'}"
        for t in reversed(recent)
    )

    return (
        "PAST TRADING PERFORMANCE (use to calibrate your confidence):\n"
        f"• {len(closed)} closed trades | Win rate: {win_rate:.0f}% | "
        f"Avg win: +{avg_win:.1f}% | Avg loss: {avg_loss:.1f}%\n"
        f"• BUY trades won: {wr(buy_closed)} | SELL trades won: {wr(sell_closed)}\n"
        f"• Recent (newest first): {recent_str}"
    )
