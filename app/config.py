import os
from dotenv import load_dotenv

load_dotenv()

BYBIT_KEY = os.getenv("BYBIT_KEY", "").strip()
BYBIT_SECRET = os.getenv("BYBIT_SECRET", "").strip()

TESTNET_RAW = os.getenv("TESTNET", "true").strip().lower()
TESTNET = TESTNET_RAW in ("1", "true", "yes", "y", "on")

if not BYBIT_KEY or not BYBIT_SECRET:
    # Не падаем жёстко, просто предупреждение будет в /health
    pass
