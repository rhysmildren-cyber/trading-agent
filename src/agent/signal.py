"""SMA-50 trend signal with deadband hysteresis. Pure functions only."""

from dataclasses import dataclass

from agent.config import DEADBAND, SMA_WINDOW


@dataclass(frozen=True)
class SignalResult:
    signal: str          # "buy" | "sell" | "hold"
    price: float
    sma: float
    in_deadband: bool


def compute_sma(closes: list[float], window: int = SMA_WINDOW) -> float:
    if len(closes) < window:
        raise ValueError(f"need {window} closes, got {len(closes)}")
    return sum(closes[-window:]) / window


def rsi_wilder(closes: list[float], period: int = 14) -> float:
    """Wilder-smoothed RSI over the full provided history."""
    if len(closes) < period + 1:
        raise ValueError(f"need {period + 1} closes, got {len(closes)}")
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    avg_gain = sum(max(d, 0) for d in deltas[:period]) / period
    avg_loss = sum(max(-d, 0) for d in deltas[:period]) / period
    for d in deltas[period:]:
        avg_gain = (avg_gain * (period - 1) + max(d, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0)) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def evaluate(price: float, sma: float, position: str, deadband: float = DEADBAND) -> SignalResult:
    """position is the current state: "long" or "flat".

    Only crossing the band switches state; inside the band we hold whatever we are.
    """
    upper = sma * (1 + deadband)
    lower = sma * (1 - deadband)
    in_deadband = lower <= price <= upper

    if price > upper and position == "flat":
        sig = "buy"
    elif price < lower and position == "long":
        sig = "sell"
    else:
        sig = "hold"
    return SignalResult(signal=sig, price=price, sma=sma, in_deadband=in_deadband)
