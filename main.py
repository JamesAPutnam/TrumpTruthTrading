import argparse
import time
import logging
from pathlib import Path
from analyzer import TradeSignal
import config
import scraper
import trade_tracker
from analyzer import analyze_post
from trader import execute_trade, is_market_open

Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/pipeline.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("main")


def execute_pending_signals():
    """At market open, fire any EXTREME signals that were queued overnight."""
    trade_tracker.purge_expired_pending()
    pending = trade_tracker.get_pending_signals()
    if not pending:
        return
    if not is_market_open():
        return

    logger.info(f"Market open — executing {len(pending)} queued EXTREME signal(s)")
    for entry in pending:
        signal = TradeSignal(
            market_relevant=True,
            tickers=entry["tickers"],
            signal=entry["signal"],
            confidence="EXTREME",
            reasoning=f"[QUEUED] {entry['reasoning']}",
            post_id=entry["post_id"],
        )
        execute_trade(signal)
        trade_tracker.remove_pending_signal(entry["post_id"])


def process_post(post: dict, performance_context: str = "") -> bool:
    text = scraper.strip_html(post.get("content", ""))
    if not text:
        return False

    logger.info(f"[{post['id']}] {text[:160]}{'...' if len(text) > 160 else ''}")

    signal = analyze_post(text, post["id"], performance_context=performance_context)
    logger.info(
        f"  -> {signal.signal} | {signal.confidence} | "
        f"relevant={signal.market_relevant} | tickers={signal.tickers}"
    )
    if signal.reasoning:
        logger.info(f"  -> {signal.reasoning}")

    traded = False
    if signal.market_relevant and signal.confidence in ("HIGH", "EXTREME"):
        traded = execute_trade(signal)
        if traded:
            logger.info("  -> TRADE EXECUTED")
        elif signal.confidence == "EXTREME" and not is_market_open():
            logger.info("  -> EXTREME signal queued for market open")

    scraper.log_post(post, signal.signal, signal.confidence, signal.tickers, traded)
    return traded


def run_once():
    scraper.ensure_data_dir()
    execute_pending_signals()
    trade_tracker.check_and_close_trades()
    perf_context = trade_tracker.build_performance_context()
    if perf_context:
        logger.info("Performance context loaded")

    account_id = scraper.get_trump_account_id()
    last_id = scraper.get_last_post_id()
    logger.info(f"Single-pass poll | last_post_id={last_id}")

    posts = scraper.fetch_new_posts(account_id, since_id=last_id)
    posts = scraper.filter_original_posts(posts)

    if not posts:
        logger.info("No new original posts.")
        return

    posts = list(reversed(posts))  # oldest-first
    logger.info(f"Found {len(posts)} new original post(s)")

    for post in posts:
        process_post(post, performance_context=perf_context)
        scraper.save_last_post_id(post["id"])

    logger.info(f"Done. last_post_id → {posts[-1]['id']}")


def run_loop():
    scraper.ensure_data_dir()
    account_id = scraper.get_trump_account_id()

    logger.info("=" * 60)
    logger.info("TrumpTruthTrading — continuous mode")
    logger.info(f"Poll interval : {config.POLL_INTERVAL_SECONDS}s")
    logger.info(f"Paper trading : {config.ALPACA_PAPER}")
    logger.info("=" * 60)

    while True:
        try:
            execute_pending_signals()
            trade_tracker.check_and_close_trades()
            perf_context = trade_tracker.build_performance_context()

            last_id = scraper.get_last_post_id()
            posts = scraper.fetch_new_posts(account_id, since_id=last_id)
            posts = scraper.filter_original_posts(posts)

            if posts:
                posts = list(reversed(posts))
                logger.info(f"Found {len(posts)} new original post(s)")
                for post in posts:
                    process_post(post, performance_context=perf_context)
                    scraper.save_last_post_id(post["id"])
            else:
                logger.debug("No new posts")

        except KeyboardInterrupt:
            logger.info("Shutting down")
            break
        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)

        time.sleep(config.POLL_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser(description="TrumpTruthTrading pipeline")
    parser.add_argument("--once", action="store_true", help="Single pass then exit (CI mode)")
    args = parser.parse_args()
    run_once() if args.once else run_loop()


if __name__ == "__main__":
    main()
