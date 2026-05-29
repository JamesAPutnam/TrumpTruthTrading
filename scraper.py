import csv
import re
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path
import config

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
LAST_POST_ID_FILE = DATA_DIR / "last_post_id.txt"
ACCOUNT_ID_CACHE = DATA_DIR / "trump_id.txt"
POSTS_LOG = DATA_DIR / "posts_log.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TrumpTruthTrading/1.0)",
    "Accept": "application/json",
}

POSTS_LOG_FIELDS = ["id", "created_at", "scraped_at", "content_preview", "signal", "confidence", "tickers", "traded"]


def ensure_data_dir():
    DATA_DIR.mkdir(exist_ok=True)
    if not POSTS_LOG.exists():
        with open(POSTS_LOG, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=POSTS_LOG_FIELDS).writeheader()


def get_trump_account_id() -> str:
    if ACCOUNT_ID_CACHE.exists():
        cached = ACCOUNT_ID_CACHE.read_text().strip()
        if cached:
            return cached

    resp = requests.get(
        f"{config.TRUTH_SOCIAL_BASE}/accounts/lookup",
        params={"acct": config.TRUMP_ACCOUNT_HANDLE},
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    account_id = resp.json()["id"]
    ACCOUNT_ID_CACHE.write_text(account_id)
    logger.info(f"Resolved Trump account ID: {account_id}")
    return account_id


def get_last_post_id() -> str | None:
    if LAST_POST_ID_FILE.exists():
        val = LAST_POST_ID_FILE.read_text().strip()
        return val if val else None
    return None


def save_last_post_id(post_id: str):
    LAST_POST_ID_FILE.write_text(post_id)


def fetch_new_posts(account_id: str, since_id: str | None = None) -> list[dict]:
    params: dict = {"limit": 20, "exclude_replies": "true"}
    if since_id:
        params["min_id"] = since_id

    resp = requests.get(
        f"{config.TRUTH_SOCIAL_BASE}/accounts/{account_id}/statuses",
        params=params,
        headers=HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def log_post(post: dict, signal_str: str, confidence: str, tickers: list[str], traded: bool):
    """Append post to the CSV log."""
    text = strip_html(post.get("content", ""))
    with open(POSTS_LOG, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=POSTS_LOG_FIELDS)
        writer.writerow({
            "id": post["id"],
            "created_at": post["created_at"],
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "content_preview": text[:200],
            "signal": signal_str,
            "confidence": confidence,
            "tickers": ",".join(tickers),
            "traded": traded,
        })


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()
