"""
╔══════════════════════════════════════════════════════════════╗
║   MEXC PENDULUM ALERT BOT v5 — амплитуда + скорость         ║
╚══════════════════════════════════════════════════════════════╝

Улучшения v5:
  - Проверка амплитуды: каждое качание проходит ≥70% ширины канала
  - Скорость маятника: сколько свечей занимает одно качание
  - Среднее время качания вверх и вниз отдельно
  - Прогноз: когда ожидать следующий разворот

Установка:  pip3 install requests python-dotenv
.env:       TG_TOKEN=...
Запуск:     python3 mexc_range_bot.py
"""

import time, requests, os, json, threading
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()

# ═══════════════════════════════════════════════════════════
#  ⚙️  НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════
TG_TOKEN  = os.getenv("TG_TOKEN", "")

CHECK_INTERVAL   = 60
CANDLE_COUNT     = 30
CANDLE_INTERVAL  = "Min15"   # 15 минут
CANDLE_MINUTES   = 15        # минут в одной свече

LEVEL_TOLERANCE  = 0.35      # допуск кластеризации уровней (%)
MIN_TOUCHES      = 3         # минимум касаний каждой границы
MIN_ALT          = 4         # минимум чередований
MIN_WIDTH_PCT    = 0.6       # минимальная ширина канала (%)
MAX_WIDTH_PCT    = 5.0       # максимальная ширина канала (%)
ALERT_PCT        = 0.35      # алерт когда цена ближе X% к границе
COOLDOWN_SEC     = 600
RECENT_CHECK     = 5         # последних свечей должны быть в канале
MIN_COVERAGE_PCT = 60.0      # % свечей внутри канала

# Каждое качание должно проходить минимум X% ширины канала
MIN_SWING_AMPLITUDE = 0.70   # 70%

ORDERBOOK_DEPTH  = 20
SUBSCRIBERS_FILE = "subscribers.json"
BASE_URL         = "https://contract.mexc.com"

# ═══════════════════════════════════════════════════════════
#  ПОДПИСЧИКИ
# ═══════════════════════════════════════════════════════════
def load_subs() -> set:
    try:
        with open(SUBSCRIBERS_FILE) as f: return set(json.load(f))
    except: return set()

def save_subs(s: set):
    with open(SUBSCRIBERS_FILE, "w") as f: json.dump(list(s), f)

subscribers = load_subs()

# ═══════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════
def tg_send(chat_id, text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=5,
        )
    except: pass

def broadcast(text: str):
    for cid in list(subscribers):
        tg_send(cid, text)
        time.sleep(0.05)

# ═══════════════════════════════════════════════════════════
#  TELEGRAM POLLING
# ═══════════════════════════════════════════════════════════
def handle_updates():
    global subscribers
    last_id = 0
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates",
                params={"offset": last_id + 1, "timeout": 30},
                timeout=35,
            )
            for upd in r.json().get("result", []):
                last_id = upd["update_id"]
                msg  = upd.get("message", {})
                if not msg: continue
                cid  = msg["chat"]["id"]
                text = msg.get("text", "").strip().lower()
                name = msg["from"].get("first_name", "друг")

                if text == "/start":
                    subscribers.add(cid); save_subs(subscribers)
                    tg_send(cid,
                        f"👋 Привет, <b>{name}</b>!\n\n"
                        f"✅ Подписан на MEXC Pendulum Bot\n\n"
                        f"Бот ищет акции с чётким маятниковым движением "
                        f"и присылает сигнал когда цена у границы канала.\n\n"
                        f"/stop — отписаться\n/stats — статистика"
                    )
                    print(f"  [+] {name} ({cid})")
                elif text == "/stop":
                    subscribers.discard(cid); save_subs(subscribers)
                    tg_send(cid, "👋 Отписан. /start — подписаться снова.")
                    print(f"  [-] {name} ({cid})")
                elif text == "/stats":
                    tg_send(cid,
                        f"📊 <b>Статистика</b>\n"
                        f"👥 Подписчиков: {len(subscribers)}\n"
                        f"⏰ Запущен: {START_TIME}\n"
                        f"📈 {CANDLE_INTERVAL} × {CANDLE_COUNT} свечей"
                    )
        except Exception as e:
            print(f"  [TG err] {e}"); time.sleep(5)

# ═══════════════════════════════════════════════════════════
#  MEXC
# ═══════════════════════════════════════════════════════════
def get_symbols() -> list:
    try:
        r = requests.get(f"{BASE_URL}/api/v1/contract/detail", timeout=10)
        result = []
        for item in r.json().get("data", []):
            sym = item.get("symbol", "")
            if "STOCK" in sym and "USDT" in sym and item.get("state") == 0:
                result.append(sym)
        for e in ["COPUSDT", "HOODUSDT", "COINUSDT"]:
            if e not in result: result.append(e)
        return result
    except:
        return ["LMTSTOCKUSDT","RTXSTOCKUSDT","COPUSDT","HOODUSDT",
                "COINUSDT","TSLASTOCKUSDT","NVDASTOCKUSDT"]

def get_candles(symbol: str) -> list:
    try:
        r = requests.get(
            f"{BASE_URL}/api/v1/contract/kline/{symbol}",
            params={"interval": CANDLE_INTERVAL, "limit": CANDLE_COUNT},
            timeout=5,
        )
        d = r.json()
        if not d.get("success"): return []
        raw = d["data"]
        return [
            {"time": raw["time"][i], "high": float(raw["high"][i]),
             "low":  float(raw["low"][i]),  "close": float(raw["close"][i])}
            for i in range(len(raw["time"]))
        ]
    except: return []

def get_price(symbol: str) -> float:
    try:
        r = requests.get(f"{BASE_URL}/api/v1/contract/ticker",
                         params={"symbol": symbol}, timeout=3)
        return float(r.json()["data"]["lastPrice"])
    except: return 0.0

def get_orderbook(symbol: str) -> dict | None:
    try:
        r = requests.get(f"{BASE_URL}/api/v1/contract/depth/{symbol}",
                         params={"limit": ORDERBOOK_DEPTH}, timeout=3)
        d = r.json()
        if not d.get("success"): return None
        bids = d["data"].get("bids", []); asks = d["data"].get("asks", [])
        if not bids or not asks: return None
        bb  = float(bids[0][0]); ba = float(asks[0][0])
        bv  = sum(float(b[0])*float(b[1]) for b in bids)
        av  = sum(float(a[0])*float(a[1]) for a in asks)
        tot = bv + av
        return {"best_bid": bb, "best_ask": ba,
                "spread_pct": (ba-bb)/bb*100, "bid_volume": bv,
                "ask_volume": av,
                "imbalance_pct": (bv-av)/tot*100 if tot > 0 else 0}
    except: return None

# ═══════════════════════════════════════════════════════════
#  ДЕТЕКТОР МАЯТНИКА v5
# ═══════════════════════════════════════════════════════════
def find_pivots(candles):
    """Находим пики и впадины с окном ±2 свечи"""
    peaks, troughs = [], []
    for i in range(2, len(candles) - 2):
        h = candles[i]["high"]
        if (h > candles[i-1]["high"] and h > candles[i-2]["high"] and
                h > candles[i+1]["high"] and h > candles[i+2]["high"]):
            peaks.append((i, h))
        l = candles[i]["low"]
        if (l < candles[i-1]["low"] and l < candles[i-2]["low"] and
                l < candles[i+1]["low"] and l < candles[i+2]["low"]):
            troughs.append((i, l))
    return peaks, troughs

def cluster_levels(points):
    if not points: return []
    clusters, used = [], [False]*len(points)
    for i, (idx, v) in enumerate(points):
        if used[i]: continue
        group = [(idx, v)]; used[i] = True
        for j in range(i+1, len(points)):
            if not used[j] and abs(points[j][1]-v)/v*100 <= LEVEL_TOLERANCE:
                group.append(points[j]); used[j] = True
        avg = sum(g[1] for g in group)/len(group)
        clusters.append((avg, len(group), [g[0] for g in group]))
    return sorted(clusters, key=lambda x: -x[1])

def analyze_swings(all_pivots: list, candles: list,
                   support: float, resistance: float) -> dict:
    """
    Анализируем качания маятника:
    - амплитуда каждого качания
    - скорость (свечей на качание)
    - среднее время вверх / вниз
    """
    if len(all_pivots) < 2:
        return {}

    channel_width = resistance - support
    swing_durations_up   = []  # свечей от впадины до пика
    swing_durations_down = []  # свечей от пика до впадины
    swing_amplitudes     = []  # амплитуда каждого качания (% от ширины)

    for i in range(1, len(all_pivots)):
        prev_type, prev_idx, prev_val = all_pivots[i-1]
        curr_type, curr_idx, curr_val = all_pivots[i]

        duration = abs(curr_idx - prev_idx)  # свечей
        amplitude = abs(curr_val - prev_val) / channel_width  # % от ширины канала

        swing_amplitudes.append(amplitude)

        if prev_type == "trough" and curr_type == "peak":
            swing_durations_up.append(duration)
        elif prev_type == "peak" and curr_type == "trough":
            swing_durations_down.append(duration)

    avg_up   = sum(swing_durations_up)   / len(swing_durations_up)   if swing_durations_up   else 0
    avg_down = sum(swing_durations_down) / len(swing_durations_down) if swing_durations_down else 0
    avg_amp  = sum(swing_amplitudes)     / len(swing_amplitudes)     if swing_amplitudes     else 0
    min_amp  = min(swing_amplitudes)     if swing_amplitudes         else 0

    # Последний пивот — откуда ждём следующее движение
    last_type, last_idx, _ = all_pivots[-1]
    candles_since_last = len(candles) - 1 - last_idx

    # Прогноз следующего разворота
    if last_type == "peak":
        expected_duration = avg_down
        next_direction    = "вниз ↓"
    else:
        expected_duration = avg_up
        next_direction    = "вверх ↑"

    candles_left = max(0, int(expected_duration) - candles_since_last)
    mins_left    = candles_left * CANDLE_MINUTES

    return {
        "avg_up_candles":   avg_up,
        "avg_down_candles": avg_down,
        "avg_up_mins":      avg_up   * CANDLE_MINUTES,
        "avg_down_mins":    avg_down * CANDLE_MINUTES,
        "avg_amplitude":    avg_amp  * 100,
        "min_amplitude":    min_amp  * 100,
        "next_direction":   next_direction,
        "candles_left":     candles_left,
        "mins_left":        mins_left,
        "last_pivot_type":  last_type,
    }

def detect_pendulum(candles: list) -> dict | None:
    if len(candles) < 15: return None

    peaks, troughs = find_pivots(candles)
    if len(peaks) < MIN_TOUCHES or len(troughs) < MIN_TOUCHES: return None

    pc = cluster_levels(peaks)
    tc = cluster_levels(troughs)
    br = next((c for c in pc if c[1] >= MIN_TOUCHES), None)
    bs = next((c for c in tc if c[1] >= MIN_TOUCHES), None)
    if not br or not bs: return None

    resistance, rt, _ = br
    support,    st, _ = bs
    if support >= resistance: return None

    width = (resistance - support) / support * 100
    if not (MIN_WIDTH_PCT <= width <= MAX_WIDTH_PCT): return None

    # Нулевые пробои
    for c in candles:
        if c["close"] > resistance * (1 + LEVEL_TOLERANCE/100): return None
        if c["close"] < support    * (1 - LEVEL_TOLERANCE/100): return None

    # Собираем все пивоты у границ
    all_pivots = sorted(
        [("peak",   i, v) for i, v in peaks   if abs(v-resistance)/resistance*100 <= LEVEL_TOLERANCE*2] +
        [("trough", i, v) for i, v in troughs if abs(v-support)/support*100       <= LEVEL_TOLERANCE*2],
        key=lambda x: x[1]
    )

    alt = sum(1 for i in range(1, len(all_pivots))
              if all_pivots[i][0] != all_pivots[i-1][0])
    if alt < MIN_ALT: return None

    # Последние RECENT_CHECK свечей в канале
    for c in candles[-RECENT_CHECK:]:
        if c["high"] > resistance*1.002 or c["low"] < support*0.998: return None

    # Покрытие
    inside = sum(1 for c in candles
                 if support*0.998 <= c["close"] <= resistance*1.002)
    coverage = inside / len(candles) * 100
    if coverage < MIN_COVERAGE_PCT: return None

    # ── ГЛАВНАЯ НОВАЯ ПРОВЕРКА: амплитуда качаний ──
    # Каждое качание должно проходить ≥ MIN_SWING_AMPLITUDE ширины канала
    channel_width = resistance - support
    for i in range(1, len(all_pivots)):
        swing_range = abs(all_pivots[i][2] - all_pivots[i-1][2])
        if swing_range / channel_width < MIN_SWING_AMPLITUDE:
            return None  # качание слишком маленькое — это не маятник

    # Анализ скорости
    speed = analyze_swings(all_pivots, candles, support, resistance)

    return {
        "support":     support,
        "resistance":  resistance,
        "width_pct":   width,
        "s_touches":   st,
        "r_touches":   rt,
        "alternating": alt,
        "coverage":    coverage,
        "swings":      len(all_pivots),
        "last_close":  candles[-1]["close"],
        "speed":       speed,
    }

# ═══════════════════════════════════════════════════════════
#  СИГНАЛ
# ═══════════════════════════════════════════════════════════
def check_signal(price: float, p: dict) -> str | None:
    if 0 <= (price - p["support"])    / p["support"]    * 100 <= ALERT_PCT: return "buy"
    if 0 <= (p["resistance"] - price) / p["resistance"] * 100 <= ALERT_PCT: return "sell"
    return None

def fmt_vol(v: float) -> str:
    if v >= 1_000_000: return f"{v/1_000_000:.2f}M"
    if v >= 1_000:     return f"{v/1_000:.1f}K"
    return f"{v:.1f}"

# ═══════════════════════════════════════════════════════════
#  ФОРМАТИРОВАТЬ АЛЕРТ
# ═══════════════════════════════════════════════════════════
def format_msg(symbol, price, signal, p, ob) -> str:
    name   = symbol.replace("USDT","").replace("STOCK","")
    emoji  = "🟢" if signal == "buy" else "🔴"
    action = "ПОКУПАТЬ ЛОНГ" if signal == "buy" else "ПРОДАВАТЬ ШОРТ"
    border = "поддержки" if signal == "buy" else "сопротивления"
    t      = datetime.now().strftime("%H:%M:%S")
    sp     = p["speed"]

    msg = (
        f"{emoji} <b>{name}</b> — {action}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Цена    : <b>{price:.3f}</b>\n"
        f"📊 Канал   : {p['support']:.3f} — {p['resistance']:.3f}\n"
        f"📏 Ширина  : {p['width_pct']:.2f}%\n"
        f"🎯 Граница : {border}\n"
        f"🔄 Качаний : {p['swings']} | Черед.: {p['alternating']}\n"
        f"📐 Покрытие: {p['coverage']:.0f}% свечей в канале\n"
    )

    # Скорость маятника
    if sp:
        msg += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ Скорость маятника:\n"
            f"   Вверх ↑ : ~{sp['avg_up_mins']:.0f} мин ({sp['avg_up_candles']:.1f} свечей)\n"
            f"   Вниз  ↓ : ~{sp['avg_down_mins']:.0f} мин ({sp['avg_down_candles']:.1f} свечей)\n"
            f"   Амплитуда: {sp['avg_amplitude']:.0f}% ширины канала\n"
        )
        if sp.get("mins_left", 0) > 0:
            msg += (
                f"   Разворот : {sp['next_direction']} "
                f"через ~{sp['mins_left']:.0f} мин\n"
            )
        else:
            msg += f"   Разворот : {sp['next_direction']} ожидается сейчас\n"

    # Стакан
    if ob:
        imb     = ob["imbalance_pct"]
        imb_str = (f"🟢 покупатели +{imb:.1f}%" if imb > 5 else
                   f"🔴 продавцы {imb:.1f}%"    if imb < -5 else
                   f"⚖️ баланс {imb:+.1f}%")
        if signal == "buy":
            verdict = ("💪 Стакан подтверждает" if imb > 5  else
                       "⚠️ Стакан против"       if imb < -10 else
                       "📊 Нейтральный")
        else:
            verdict = ("💪 Стакан подтверждает" if imb < -5 else
                       "⚠️ Стакан против"       if imb > 10  else
                       "📊 Нейтральный")
        sp_ok = "✅" if ob["spread_pct"] < 0.1 else ("⚠️" if ob["spread_pct"] < 0.3 else "❌")
        msg += (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📖 Стакан:\n"
            f"   Bid: {ob['best_bid']:.3f}  │  Ask: {ob['best_ask']:.3f}\n"
            f"   Спред: <b>{ob['spread_pct']:.3f}%</b> {sp_ok}\n"
            f"   Объём bid: {fmt_vol(ob['bid_volume'])} │ ask: {fmt_vol(ob['ask_volume'])}\n"
            f"   {imb_str} | {verdict}\n"
        )

    msg += (
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {t}\n"
        f"🔗 futures.mexc.com/exchange/{symbol}"
    )
    return msg

# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════
START_TIME = datetime.now().strftime("%d.%m %H:%M")

def main():
    global subscribers
    print("╔══════════════════════════════════════════════════════╗")
    print("║   MEXC PENDULUM BOT v5 — амплитуда + скорость       ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    if not TG_TOKEN:
        print("  ❌ Заполни TG_TOKEN в .env!"); return

    threading.Thread(target=handle_updates, daemon=True).start()
    print("  ✅ Telegram polling запущен")

    symbols = get_symbols()
    print(f"  Акций: {len(symbols)} | Подписчиков: {len(subscribers)}\n")

    if subscribers:
        broadcast(
            f"🤖 <b>MEXC Pendulum Bot v5</b>\n"
            f"Мониторю {len(symbols)} акций\n"
            f"Новое: скорость и амплитуда маятника\n"
            f"@mexcsharesalertnk_bot"
        )

    cooldowns = {}
    iteration = 0

    while True:
        iteration += 1
        now = datetime.now().strftime("%H:%M:%S")
        found = sent = 0

        print(f"  [{now}] Итер.{iteration} | акций={len(symbols)} | подп.={len(subscribers)}")

        for symbol in symbols:
            try:
                if time.time() - cooldowns.get(symbol, 0) < COOLDOWN_SEC:
                    continue

                candles = get_candles(symbol)
                if len(candles) < 15: continue

                p = detect_pendulum(candles)
                if not p: continue

                found += 1
                price = get_price(symbol)
                if not price: continue

                signal = check_signal(price, p)
                if not signal: continue

                ob  = get_orderbook(symbol)
                msg = format_msg(symbol, price, signal, p, ob)
                broadcast(msg)
                cooldowns[symbol] = time.time()
                sent += 1

                name = symbol.replace("USDT","").replace("STOCK","")
                sp   = p["speed"]
                spd  = f"↑{sp['avg_up_mins']:.0f}м/↓{sp['avg_down_mins']:.0f}м" if sp else ""
                print(f"  🔔 {name} {'BUY' if signal=='buy' else 'SELL'} "
                      f"@ {price:.3f} | {spd} амп={sp.get('avg_amplitude',0):.0f}%")

                time.sleep(0.3)
            except Exception:
                continue

        print(f"  Маятников: {found} | Алертов: {sent}\n")

        if iteration % 20 == 0:
            new = get_symbols()
            if new: symbols = new

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
