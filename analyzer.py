import json
import logging
from dataclasses import dataclass, field
import anthropic
import config

logger = logging.getLogger(__name__)

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


SYSTEM_PROMPT = """You are a conservative stock trading signal analyst monitoring Donald Trump's Truth Social posts for market-moving statements.

Your task is to determine whether each post contains a high-confidence, actionable stock trading signal.

STRICT criteria for HIGH confidence:
- Trump DIRECTLY names a specific public company (e.g., "Apple", "Tesla", "Amazon") AND expresses clear sentiment
- Trump announces a concrete policy targeting a specific industry in a way that clearly benefits or harms specific sectors
- Examples of HIGH BUY: "I love what [Company] is doing for America", "[Company] CEO called me, great guy, amazing things ahead"
- Examples of HIGH SELL: "[Company] is ripping off Americans", "We're going after [Company]", explicit tariff on a single sector

DO NOT trade on:
- General economy/inflation/interest rate comments
- Political attacks on people (not companies)
- Vague national pride posts
- Social commentary without corporate/sector specificity
- Reposts or shares of others' content without Trump's own clear stance

When you identify relevant tickers, use their NYSE/NASDAQ symbol (e.g., TSLA not Tesla, AAPL not Apple).
For sector ETFs when appropriate: defense → LMT/RTX/NOC, energy → XOM/CVX, China trade → FXI.

Respond ONLY with valid JSON, no other text:
{
  "market_relevant": true or false,
  "tickers": ["TICK1", "TICK2"],
  "signal": "BUY" or "SELL" or "HOLD",
  "confidence": "HIGH" or "MEDIUM" or "LOW",
  "reasoning": "one sentence explanation"
}"""


@dataclass
class TradeSignal:
    market_relevant: bool
    tickers: list[str] = field(default_factory=list)
    signal: str = "HOLD"
    confidence: str = "LOW"
    reasoning: str = ""
    post_id: str = ""


def analyze_post(post_text: str, post_id: str, performance_context: str = "") -> TradeSignal:
    try:
        client = _get_client()
        user_content = f"Analyze this Truth Social post:\n\n{post_text}"
        if performance_context:
            user_content = f"{performance_context}\n\n---\n\n{user_content}"

        message = client.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=400,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": user_content,
                }
            ],
        )

        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)

        return TradeSignal(
            market_relevant=bool(data.get("market_relevant", False)),
            tickers=[t.upper() for t in data.get("tickers", [])],
            signal=data.get("signal", "HOLD").upper(),
            confidence=data.get("confidence", "LOW").upper(),
            reasoning=data.get("reasoning", ""),
            post_id=post_id,
        )

    except Exception as e:
        logger.error(f"LLM analysis failed for post {post_id}: {e}")
        return TradeSignal(
            market_relevant=False,
            reasoning=f"Analysis error: {e}",
            post_id=post_id,
        )
