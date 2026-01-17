import ccxt
import requests
import os
import time
import pandas as pd
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange


#TG_TOKEN = os.getenv("TG_TOKEN")
#TG_CHAT_ID = os.getenv("TG_CHAT_ID")

TG_TOKEN = "8591772937:AAFzgMJILNWhqWu5cPvgZyBwzX7TDZ5sMqo"
TG_CHAT_ID = "490648412"

#ex = ccxt.binance({"enableRateLimit": True})
def fetch_ohlcv(symbol, limit=200):
    # 15m = 15 минут => берем histominute и aggregate=15
    base = symbol.split("/")[0]  # BTC из BTC/USDT
    url = "https://min-api.cryptocompare.com/data/v2/histominute"
    params = {"fsym": base, "tsym": "USDT", "limit": limit, "aggregate": 15}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()["Data"]["Data"]

    ohlcv = []
    for c in data:
        ts_ms = int(c["time"]) * 1000
        ohlcv.append([ts_ms, c["open"], c["high"], c["low"], c["close"], c["volumefrom"]])
    return ohlcv


def send(msg):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    r =requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg})
    print("TG status: ", r.status_code)
    print("TG resp: ", r.text)

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
TIMEFRAME = "15m"
LIMIT = 200

K_ATR = 3.0
RR = 2.0
LOOKBACK = 50
MIN_DIST_PCT = 1.0
MIN_TP_BTC = 0.45
MIN_TP_ALT = 0.60

SLEEP_SEC = 900
def run_once():
    STATE_FILE = "last_signal.txt"
    last_state = ""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            last_state = f.read().strip()

    blocks_console = []
    blocks_tg = []
    state_parts = []

    for symbol in SYMBOLS:
        #ohlcv = ex.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=LIMIT)
        ohlcv = fetch_ohlcv(symbol, limit=LIMIT)
        df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df["rsi"] = RSIIndicator(df["close"], window=14).rsi()
        df["ma7"] = df["close"].rolling(7).mean()
        df["ma14"] = df["close"].rolling(14).mean()
        df["ma28"] = df["close"].rolling(28).mean()

        last = df.iloc[-2]  # закрытая свеча
        price = float(last["close"])
        rsi = float(last["rsi"])
        ma7 = float(last["ma7"])
        ma14 = float(last["ma14"])
        ma28 = float(last["ma28"])

        trend_up = ma7 > ma14 > ma28
        trend_down = ma7 < ma14 < ma28

        reasons = []

        recent_high = df["high"].iloc[-LOOKBACK:].max()
        recent_low  = df["low"].iloc[-LOOKBACK:].min()
        dist_to_high = (recent_high - price) / price * 100
        dist_to_low  = (price - recent_low) / price * 100
        near_resistance = dist_to_high < MIN_DIST_PCT
        near_support    = dist_to_low  < MIN_DIST_PCT

        atr = AverageTrueRange(high=df["high"], low=df["low"], close=df["close"], window=14).average_true_range()
        atr_val = float(atr.iloc[-2])
        sl_pct = (K_ATR * atr_val / price) * 100
        tp_pct = sl_pct * RR
        min_tp = MIN_TP_BTC if symbol == "BTC/USDT" else MIN_TP_ALT
        tp_ok = tp_pct >= min_tp
        near_long = trend_up and (30 <= rsi <= 35) and (not near_resistance)
        near_short = trend_down and (65 <= rsi <= 70) and (not near_support)

        if rsi < 30 and trend_up and not near_resistance and tp_ok:
            signal = "🟢 LONG"
        elif rsi > 70 and trend_down and not near_support and tp_ok:
            signal = "🔴 SHORT"
        elif near_long and tp_ok:
            signal = "🟡 LONG близко (RSI 30–35)"
        elif near_short and tp_ok:
            signal = "🟠 SHORT близко (RSI 65–70)"
        else:
            signal = "—"

        # ✅ Формируем и добавляем block ТОЛЬКО если есть сигнал/почти сигнал

        block = (
            f"{symbol} {TIMEFRAME}\n"
            f"price: {price:.2f}\n"
            f"RSI14: {rsi:.2f}\n"
            f"ma7: {ma7:.2f}\n"
            f"ma14: {ma14:.2f}\n"
            f"ma28: {ma28:.2f}\n"
            f"distHigh: {dist_to_high:.2f}%\n"
            f"distLow: {dist_to_low:.2f}%\n"
            f"ATR14: {atr_val:.2f}\n"
            f"SL: {sl_pct:.2f}%  TP: {tp_pct:.2f}% (RR={RR})\n"
            f"TP filter: {'Потенцаил прибыли: Достоточный' if tp_ok else 'Потенцаил прибыли: Слабый'} (min {min_tp})\n"
            f"{signal}\n"
            )
        blocks_console.append(block)

        # Формируем подробный блок ТОЛЬКО если есть сигнал/близко
        if signal != "—":
            blocks_tg.append(block)
            state_parts.append(f"{symbol}:{signal}")

    message_console = "🖥 Консоль (все монеты):\n\n" + "\n".join(blocks_console)
    print(message_console)

    message_tg = "📌 Telegram (только сигналы/почти сигналы):\n\n" + (
        "\n".join(blocks_tg) if blocks_tg else "Сигналов нет"
    )

    new_state = "|".join(state_parts)

    if blocks_tg and new_state != last_state:
        send(message_tg)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(new_state)

if __name__ == "__main__":
    while True:
        try:
            run_once()
        except Exception as e:
            print("Ошибка в боте", e)
        time.sleep(SLEEP_SEC)
