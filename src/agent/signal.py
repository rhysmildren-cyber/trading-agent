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
