"""3-sentence commentary from Claude Haiku, in English and Vietnamese.

Haiku only sees the report numbers. Every number it writes is checked against
those numbers; if it invents one, the commentary is dropped (never sent).
"""
import os
import re

import anthropic
from pydantic import BaseModel

MODEL = "claude-haiku-5-5"

SYSTEM = """You are a careful on-chain data analyst writing a daily briefing about where money is flowing in crypto.
Write exactly 3 short observations (one sentence each) in English, then the same 3 observations in Vietnamese.

Rules:
- Use ONLY numbers that appear in the data. Never compute, round differently or invent numbers. Copy numbers exactly as written (dot as decimal separator, same units).
- Fees and stablecoin flows are the reliable signals of real money. TVL is secondary because it moves with token prices: compare TVL changes with the BTC/ETH 7d price change before calling something an inflow.
- Only call a category "durable" / "nóng bền" if the data marks it DURABLE HOT. If a category is marked "mostly <protocol>", say the move is driven by that protocol.
- No buy/sell/hold advice, no price predictions, no "opportunity" language. Describe, don't recommend.
- Vietnamese: natural, concise; keep protocol, chain and category names in English."""


class Insight(BaseModel):
    en: list[str]
    vi: list[str]


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text):
    out = set()
    for n in _NUM.findall(text):
        n = n.replace(",", ".")
        out.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return out


def invented_numbers(sentences, facts):
    allowed = _numbers(facts) | {str(i) for i in range(0, 15)}  # small counts: "3 categories", "7 days"
    return sorted(_numbers(" ".join(sentences)) - allowed)


def write_insight(facts, client=None):
    """Return (Insight | None, reason). Never raises for API problems."""
    if client is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return None, "ANTHROPIC_API_KEY not set"
    try:
        client = client or anthropic.Anthropic()
        resp = client.messages.parse(
            model=MODEL,
            max_tokens=4000,
            output_config={"effort": "low"},
            system=SYSTEM,
            messages=[{"role": "user", "content": f"Data:\n{facts}"}],
            output_format=Insight,
        )
    except anthropic.APIError as e:
        return None, f"Claude API: {type(e).__name__}: {getattr(e, 'message', e)}"
    except Exception as e:  # missing key, bad schema, etc.: the numbers still go out
        return None, f"Claude: {type(e).__name__}: {e}"
    if resp.stop_reason == "refusal":
        return None, "Claude refused"
    ins = resp.parsed_output
    if not ins or len(ins.en) != 3 or len(ins.vi) != 3:
        return None, "Claude did not return 3+3 sentences"
    bad = invented_numbers(ins.en + ins.vi, facts)
    if bad:
        return None, f"Claude used numbers not in the data: {bad}"
    return ins, "ok"
