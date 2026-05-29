import argparse
import time
import logging
from pathlib import Path
import config
import scraper
import trade_tracker
from analyzer import analyze_post
from trader import execute_trade

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
    if signal.market_relevant and signal.confidence == "HIGH":
        traded = execute_trade(signal)
        if traded:
            logger.info("  -> TRADE EXECUTED")

    scraper.log_post(post, signal.signal, signal.confidence, signal.tickers, traded)
    return traded


def run_once():
    """Single pass — check outcomes, fetch new posts, process, exit. Used by GitHub Actions."""
    scraper.ensure_data_dir()

    # 1. Check if any open trades have resolved
    trade_tracker.check_and_close_trades()

    # 2. Build performance context from closed trade history
    perf_context = trade_tracker.build_performance_context()
    if perf_context:
        logger.info("Performance context loaded for LLM")

    # 3. Fetch and process new posts
    account_id = scraper.get_trump_account_id()
    last_id = scraper.get_last_post_id()
    logger.info(f"Single-pass poll | last_post_id={last_id}")

    posts = scraper.fetch_new_posts(account_id, since_id=last_id)
    if not posts:
        logger.info("No new posts.")
        return

    posts = list(reversed(posts))  # oldest-first
    logger.info(f"Found {len(posts)} new post(s)")

    for post in posts:
        process_post(post, performance_context=perf_context)
        scraper.save_last_post_id(post["id"])

    logger.info(f"Done. last_post_id → {posts[-1]['id']}")


def run_loop():
    """Continuous loop for local use."""
    scraper.ensure_data_dir()
    account_id = scraper.get_trump_account_id()

    logger.info("=" * 60)
    logger.info("TrumpTruthTrading — continuous mode")
    logger.info(f"Poll interval : {config.POLL_INTERVAL_SECONDS}s")
    logger.info(f"Paper trading : {config.ALPACA_PAPER}")
    logger.info("=" * 60)

    while True:
        try:
            trade_tracker.check_and_close_trades()
            perf_context = trade_tracker.build_performance_context()

            last_id = scraper.get_last_post_id()
            posts = scraper.fetch_new_posts(account_id, since_id=last_id)

            if posts:
                posts = list(reversed(posts))
                logger.info(f"Found {len(posts)} new post(s)")
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

    if args.once:
        run_once()
    else:
        run_loop()


if __name__ == "__main__":
    main()
