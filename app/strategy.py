from __future__ import annotations


def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema

def decide_signal(closes: list[float]) -> str:
    import random

    # 20% шанс открыть сделку каждый цикл
    r = random.random()

    if r < 0.10:
        return "BUY"
    elif r < 0.20:
        return "SELL"
    else:
        return "HOLD"



    # --- Настройки теста ---
    N = 3                 # сколько свечей назад сравниваем
    THRESH = 0.15         # порог движения в % (0.15% даст сигналы часто на BTC 5m)

    last = float(closes[-1])
    prev = float(closes[-1 - N])
    if prev <= 0:
        return "HOLD"

    change_pct = (last - prev) / prev * 100.0

    # --- Фильтр тренда (чтобы не ловить совсем шум) ---
    ema50 = _ema(closes, 50)
    if not ema50:
        return "HOLD"
    trend_up = ema50[-1] > ema50[-2]
    trend_down = ema50[-1] < ema50[-2]

    # --- Сигнал ---
    if change_pct >= THRESH and trend_up:
        return "BUY"
    if change_pct <= -THRESH and trend_down:
        return "SELL"

    return "HOLD"
