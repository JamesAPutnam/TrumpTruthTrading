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

Confidence levels — assign the HIGHEST level that fits:

EXTREME (rarest — will queue for market open even if posted overnight):
- Trump makes an explicit personal endorsement or buy/sell recommendation for a named stock
- Trump announces formal legal/executive action directly targeting a named company
- Trump references a personal meeting or deal with a named company's CEO with clear outcome
- Examples: "Everyone should buy [Company] stock", "I'm directing the DOJ to investigate [Company]", "Just signed a deal with [Company CEO], big things coming"

HIGH (will trade immediately if market is open):
- Trump directly names a specific company by name (e.g., "Tesla", "Apple") OR ticker (e.g., "$TSLA", "$AAPL") with clear positive or negative sentiment
- Trump announces sector-specific policy naming a concrete industry with obvious winners/losers
- Examples: "I love what [Company] is doing for America", "[Company] is ripping off Americans, we're going after them"

MEDIUM / LOW — do not trade:
- General economy, inflation, or interest rate comments
- Political attacks on individuals (not companies)
- Vague national pride or political posts
- Social commentary without corporate specificity

When you identify relevant tickers, use NYSE/NASDAQ symbols (TSLA not Tesla, AAPL not Apple).
Sector ETFs when appropriate: defense → LMT/RTX/NOC, energy → XOM/CVX, China trade → FXI.

Respond ONLY with valid JSON, no other text:
{
  "market_relevant": true or false,
  "tickers": ["TICK1", "TICK2"],
  "signal": "BUY" or "SELL" or "HOLD",
  "confidence": "EXTREME" or "HIGH" or "MEDIUM" or "LOW",
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
