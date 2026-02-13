from __future__ import annotations


def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        diff = values[i] - values[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - (100.0 / (1.0 + rs))


def decide_signal(closes: list[float]) -> str:
    if len(closes) < 60:
        return "HOLD"
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    if ema20[-1] > ema50[-1]:
        return "BUY"
    if ema20[-1] < ema50[-1]:
        return "SELL"
    return "HOLD"

    # тренд вверх: цена чуть ниже EMA20 (откат) + RSI не перегрет
    if e20 > e50:
        pullback = price <= e20 * 1.001  # около EMA20
        if pullback and rsi < 60:
            return "BUY"

    # тренд вниз: цена чуть выше EMA20 (откат вверх) + RSI не перепродан
    if e20 < e50:
        pullback = price >= e20 * 0.999
        if pullback and rsi > 40:
            return "SELL"

    return "HOLD"
