"""BTC/USD daily bars from Alpaca crypto market data (no API keys required)."""

from datetime import date, datetime, timedelta, timezone

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from agent.config import SYMBOL


def get_daily_closes(days: int, symbol: str = SYMBOL) -> list[tuple[date, float]]:
    """Return [(utc_date, close)] for completed daily bars, oldest first.

    Excludes today's still-forming bar so decisions always use the last
    completed daily close.
    """
    client = CryptoHistoricalDataClient()
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days + 5)  # small pad for any gaps
    req = CryptoBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start,
    )
    bars = client.get_crypto_bars(req).data[symbol]
    today = now.date()
    out = [(b.timestamp.date(), float(b.close)) for b in bars if b.timestamp.date() < today]
    return out[-days:]
