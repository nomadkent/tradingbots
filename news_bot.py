"""
╔══════════════════════════════════════════════════════════════╗
║   MARKET NEWS ALERT BOT — нефть, золото, крипта             ║
║   Без Claude AI — анализ по правилам и ключевым словам      ║
╚══════════════════════════════════════════════════════════════╝

Установка:  pip3 install requests python-dotenv feedparser
.env:       TG_TOKEN=...
Запуск:     python3 news_bot.py
"""

import time, requests, os, json, hashlib, threading, feedparser
from dotenv import load_dotenv
from datetime import datetime

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "news_bot.env"))
# Если news_bot.env не найден — пробуем обычный .env
if not os.getenv("TG_TOKEN"):
    load_dotenv()

# ═══════════════════════════════════════════════════════════
#  ⚙️  НАСТРОЙКИ
# ═══════════════════════════════════════════════════════════
TG_TOKEN         = os.getenv("TG_TOKEN", "")
CHECK_INTERVAL   = 45    # секунд между проверками
SEEN_FILE        = "seen_news.json"
SUBSCRIBERS_FILE = "subscribers_news.json"

# ═══════════════════════════════════════════════════════════
#  RSS ИСТОЧНИКИ
# ═══════════════════════════════════════════════════════════
RSS_FEEDS = [
    {"url": "https://feeds.reuters.com/reuters/businessNews",   "name": "Reuters Business"},
    {"url": "https://feeds.reuters.com/Reuters/worldNews",      "name": "Reuters World"},
    {"url": "https://oilprice.com/rss/main",                    "name": "OilPrice.com"},
    {"url": "https://www.cnbc.com/id/100727362/device/rss/rss.html", "name": "CNBC Energy"},
    {"url": "https://feeds.bbci.co.uk/news/business/rss.xml",   "name": "BBC Business"},
    {"url": "https://apnews.com/rss",                           "name": "AP News"},
    {"url": "https://feeds.bloomberg.com/markets/news.rss",     "name": "Bloomberg"},
    {"url": "https://www.ft.com/rss/home",                      "name": "Financial Times"},
    {"url": "https://trumpstruth.org/feed",                     "name": "Trump Truth Social"},
    {"url": "https://cointelegraph.com/rss",                    "name": "CoinTelegraph"},
    {"url": "https://coindesk.com/arc/outboundfeeds/rss/",      "name": "CoinDesk"},
    {"url": "https://www.investing.com/rss/news.rss",           "name": "Investing.com"},
    {"url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=19854910",
                                                                 "name": "CNBC World"},
]

# ═══════════════════════════════════════════════════════════
#  ПРАВИЛА АНАЛИЗА
#  Каждое правило: (ключевые слова, актив, направление, важность, причина)
#  Важность: critical=4, high=3, medium=2, low=1
# ═══════════════════════════════════════════════════════════
RULES = [
    # ── НЕФТЬ ВВЕРХ ────────────────────────────────────────
    (["hormuz", "strait closed", "strait blocked", "пролив закрыт"],
     "oil", "up", 4, "Закрытие Ормузского пролива — критический удар по поставкам нефти"),

    (["attack", "strike", "refinery", "нпз", "pipeline", "нефтепровод",
      "oil facility", "aramco", "oil infrastructure"],
     "oil", "up", 4, "Атака на нефтяную инфраструктуру — прямое сокращение предложения"),

    (["iran", "missile", "ballistic", "иран", "ракета"],
     "oil", "up", 3, "Иранские ракетные удары — эскалация конфликта, риск для поставок"),

    (["opec cut", "opec+ cut", "production cut", "сокращение добычи"],
     "oil", "up", 3, "ОПЕК+ сокращает добычу — меньше предложения, цена растёт"),

    (["sanctions", "embargo", "санкции", "эмбарго"],
     "oil", "up", 3, "Новые санкции — сокращение доступной нефти на рынке"),

    (["escalat", "escalation", "эскалация", "war expand", "wider war"],
     "oil", "up", 3, "Эскалация конфликта — рынок закладывает риски поставок"),

    (["eia", "api", "inventory", "stockpile draw", "drawdown", "запасы сократились"],
     "oil", "up", 2, "Сокращение запасов нефти по данным EIA/API — спрос превышает предложение"),

    (["hurricane", "storm", "gulf of mexico", "ураган"],
     "oil", "up", 2, "Ураган угрожает добыче в Мексиканском заливе"),

    # ── НЕФТЬ ВНИЗ ─────────────────────────────────────────
    (["ceasefire", "peace deal", "перемирие", "мирные переговоры", "peace talks"],
     "oil", "down", 4, "Перемирие — деэскалация конфликта, снижение геополитической премии"),

    (["hormuz open", "strait open", "пролив открыт", "navigation resumes"],
     "oil", "down", 4, "Открытие Ормузского пролива — восстановление поставок"),

    (["opec increase", "opec+ increase", "production increase", "увеличение добычи"],
     "oil", "down", 3, "ОПЕК+ увеличивает добычу — больше предложения"),

    (["recession", "demand falls", "economic slowdown", "рецессия", "падение спроса"],
     "oil", "down", 3, "Рецессия снижает спрос на нефть"),

    (["eia build", "inventory build", "запасы выросли", "surplus"],
     "oil", "down", 2, "Рост запасов нефти — предложение превышает спрос"),

    (["iran deal", "nuclear deal", "ядерная сделка", "iran agreement"],
     "oil", "down", 3, "Ядерная сделка с Ираном — снятие санкций увеличит предложение"),

    # ── ЗОЛОТО ВВЕРХ ───────────────────────────────────────
    (["gold", "золото", "xau"],
     "gold", "unclear", 1, "Новость про золото"),  # базовый фильтр, уточняется ниже

    (["uncertainty", "risk off", "safe haven", "золото растёт", "gold rises",
      "gold rally", "геополитическая напряжённость"],
     "gold", "up", 2, "Рост неопределённости — инвесторы уходят в золото"),

    (["inflation", "инфляция", "cpi", "pce"],
     "gold", "up", 2, "Высокая инфляция поддерживает золото как защитный актив"),

    (["fed cut", "rate cut", "снижение ставки", "dovish"],
     "gold", "up", 3, "Снижение ставок ФРС — доллар слабеет, золото растёт"),

    (["dollar falls", "dollar weakens", "доллар падает", "weak dollar"],
     "gold", "up", 2, "Слабый доллар — золото дорожает"),

    (["war", "война", "conflict", "конфликт", "nuclear threat"],
     "gold", "up", 2, "Военный конфликт — спрос на безопасные активы растёт"),

    # ── ЗОЛОТО ВНИЗ ────────────────────────────────────────
    (["fed hike", "rate hike", "повышение ставки", "hawkish"],
     "gold", "down", 2, "Повышение ставок ФРС — доллар крепнет, золото падает"),

    (["strong dollar", "dollar rises", "доллар растёт"],
     "gold", "down", 2, "Сильный доллар давит на золото"),

    # ── КРИПТА ВВЕРХ ───────────────────────────────────────
    (["bitcoin etf", "btc etf", "crypto etf", "etf approved", "etf одобрен"],
     "crypto", "up", 3, "Одобрение ETF — институциональные деньги входят в крипту"),

    (["bitcoin buy", "btc buy", "institutional", "microstrategy", "купил биткоин"],
     "crypto", "up", 2, "Институциональные покупки биткоина"),

    (["crypto legal", "crypto regulation positive", "легализация крипты"],
     "crypto", "up", 2, "Позитивное регулирование — рынок растёт"),

    (["halving", "хавинг", "bitcoin halving"],
     "crypto", "up", 3, "Халвинг биткоина — сокращение предложения"),

    # ── КРИПТА ВНИЗ ────────────────────────────────────────
    (["crypto ban", "bitcoin ban", "крипта запрещена", "sec charges", "sec lawsuit"],
     "crypto", "down", 3, "Регуляторное давление — рынок падает"),

    (["hack", "exploit", "взлом", "биржа взломана", "exchange hacked"],
     "crypto", "down", 3, "Взлом биржи — паника на рынке"),

    (["crypto crash", "bitcoin crash", "крипта падает"],
     "crypto", "down", 2, "Обвал крипторынка"),

    # ── ТРАМП — ОСОБЫЙ СЛУЧАЙ ──────────────────────────────
    (["trump", "трамп"],
     "oil", "unclear", 3, "Заявление Трампа — высокая волатильность, анализируй контекст"),
]

# Минимальная важность для отправки (1=low, 2=medium, 3=high, 4=critical)
MIN_IMPORTANCE = 2

# ═══════════════════════════════════════════════════════════
#  ПОДПИСЧИКИ
# ═══════════════════════════════════════════════════════════
def load_json(path, default):
    try:
        with open(path) as f: return json.load(f)
    except: return default

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f)

subscribers = set(load_json(SUBSCRIBERS_FILE, []))
seen_news   = set(load_json(SEEN_FILE, []))

# ═══════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════
def tg_send(chat_id, text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=10,
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
                    subscribers.add(cid)
                    save_json(SUBSCRIBERS_FILE, list(subscribers))
                    tg_send(cid,
                        f"👋 Привет, <b>{name}</b>!\n\n"
                        f"✅ Подписан на <b>Market News Bot</b>\n\n"
                        f"Мониторю {len(RSS_FEEDS)} источников:\n"
                        f"Reuters • Bloomberg • AP • CNBC • OilPrice\n"
                        f"Financial Times • Truth Social (Трамп) • CoinTelegraph\n\n"
                        f"Присылаю только важные новости по:\n"
                        f"🛢️ Нефть (WTI/Brent) — приоритет\n"
                        f"🥇 Золото и металлы\n"
                        f"₿ Биткоин и крипта\n\n"
                        f"/stop — отписаться\n"
                        f"/status — статус бота"
                    )
                    print(f"  [+] {name} ({cid})")

                elif text == "/stop":
                    subscribers.discard(cid)
                    save_json(SUBSCRIBERS_FILE, list(subscribers))
                    tg_send(cid, "👋 Отписан. /start — подписаться снова.")

                elif text == "/status":
                    tg_send(cid,
                        f"🤖 <b>Market News Bot</b>\n"
                        f"👥 Подписчиков: {len(subscribers)}\n"
                        f"📰 Источников: {len(RSS_FEEDS)}\n"
                        f"🔍 Новостей обработано: {len(seen_news)}\n"
                        f"⏰ Запущен: {START_TIME}"
                    )
        except Exception as e:
            print(f"  [TG err] {e}"); time.sleep(5)

# ═══════════════════════════════════════════════════════════
#  АНАЛИЗ НОВОСТИ ПО ПРАВИЛАМ
# ═══════════════════════════════════════════════════════════
ASSET_NAMES = {"oil": "Нефть 🛢️", "gold": "Золото 🥇", "crypto": "Крипта ₿"}

def analyze_by_rules(title: str, summary: str) -> dict | None:
    text = (title + " " + (summary or "")).lower()

    best = None
    best_score = 0

    for keywords, asset, direction, importance, reason in RULES:
        if importance < MIN_IMPORTANCE:
            continue
        matches = sum(1 for kw in keywords if kw.lower() in text)
        if matches == 0:
            continue

        score = importance * matches
        if score > best_score:
            best_score = score
            best = {
                "asset":      asset,
                "direction":  direction,
                "importance": importance,
                "reason":     reason,
                "matches":    matches,
            }

    if not best:
        return None

    # Уточняем направление для Трампа по контексту
    if best["asset"] == "oil" and best["direction"] == "unclear":
        if any(w in text for w in ["peace", "deal", "negotiate", "ceasefire", "перемирие"]):
            best["direction"] = "down"
        elif any(w in text for w in ["attack", "war", "strike", "bomb", "missile", "война"]):
            best["direction"] = "up"

    # Определяем сигнал
    if best["direction"] == "up":
        best["signal"] = "LONG"
    elif best["direction"] == "down":
        best["signal"] = "SHORT"
    else:
        best["signal"] = "WAIT"

    return best

# ═══════════════════════════════════════════════════════════
#  ФОРМАТИРОВАТЬ АЛЕРТ
# ═══════════════════════════════════════════════════════════
IMPORTANCE_LABEL = {4: "🚨 КРИТИЧНО", 3: "⚠️ ВАЖНО", 2: "📌 ЗАМЕТНО"}
SIGNAL_LABEL     = {"LONG": "🟢 ЛОНГ", "SHORT": "🔴 ШОРТ", "WAIT": "⏸ НАБЛЮДАТЬ"}
DIRECTION_LABEL  = {"up": "↑ ВВЕРХ", "down": "↓ ВНИЗ", "unclear": "↕ НЕЯСНО"}

def format_alert(title: str, url: str, source: str, a: dict) -> str:
    t = datetime.now().strftime("%H:%M:%S")
    return (
        f"{IMPORTANCE_LABEL.get(a['importance'], '📌')} "
        f"{ASSET_NAMES.get(a['asset'], a['asset'])}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{title}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📡 {source}\n"
        f"💡 {a['reason']}\n"
        f"📈 Ожидание: {DIRECTION_LABEL.get(a['direction'], '')}\n"
        f"🎯 Сигнал  : {SIGNAL_LABEL.get(a['signal'], a['signal'])}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ {t}\n"
        f"🔗 <a href='{url}'>Читать</a>"
    )

# ═══════════════════════════════════════════════════════════
#  СВОДКА РЫНКА (без AI — по расписанию)
# ═══════════════════════════════════════════════════════════
summary_sent = {}

def check_market_schedule():
    now     = datetime.utcnow()
    weekday = now.weekday()  # 0=пн .. 4=пт .. 6=вс
    hour    = now.hour
    minute  = now.minute

    # Пятница 21:55 UTC — за 5 мин до закрытия на выходные
    if weekday == 4 and hour == 21 and 55 <= minute <= 59:
        key = f"close_fri_{now.strftime('%Y%m%d')}"
        if key not in summary_sent:
            summary_sent[key] = True
            broadcast(
                f"📊 <b>РЫНОК WTI ЗАКРЫВАЕТСЯ НА ВЫХОДНЫЕ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ Закрытие через ~5 минут (22:00 UTC)\n"
                f"🔓 Открытие: воскресенье 23:00 UTC (02:00 МСК)\n\n"
                f"⚡ <b>Что учесть:</b>\n"
                f"• Война США-Иран продолжается — высокий риск выходных новостей\n"
                f"• Военные операции часто активизируются в выходные\n"
                f"• Трамп может написать в Truth Social в любой момент\n"
                f"• Любая новость про Ормуз = сильное движение на открытии\n\n"
                f"🎯 <b>Стратегия:</b>\n"
                f"Если хочешь поймать гэп на открытии — открой лонг+шорт "
                f"с разумным плечом (10-20x). При 5%+ движении один из них "
                f"покроет другой с хорошей прибылью.\n\n"
                f"⚠️ При 100x плече — риск двойной ликвидации на фитиле!\n"
                f"Бот будет мониторить новости всё воскресенье и сообщит "
                f"если что-то важное произойдёт."
            )
            print("  📊 Сводка: закрытие пятницы отправлена")

    # Воскресенье 22:55 UTC — за 5 мин до открытия
    elif weekday == 6 and hour == 22 and 55 <= minute <= 59:
        key = f"open_sun_{now.strftime('%Y%m%d')}"
        if key not in summary_sent:
            summary_sent[key] = True
            broadcast(
                f"📊 <b>РЫНОК WTI ОТКРЫВАЕТСЯ ЧЕРЕЗ 5 МИНУТ</b>\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"⏰ Открытие: 23:00 UTC (02:00 МСК)\n\n"
                f"🔍 <b>Что проверить перед входом:</b>\n"
                f"• Последние новости про Иран/Ормуз за выходные\n"
                f"• Посты Трампа в Truth Social\n"
                f"• Общий тон геополитики\n\n"
                f"⚡ Рынок может открыться с сильным гэпом если "
                f"за выходные произошло что-то важное.\n"
                f"Следи за первыми 5 свечами — они покажут направление."
            )
            print("  📊 Сводка: открытие воскресенья отправлена")

    # Пн-Пт 00:55 UTC — за 5 мин до ежедневного открытия
    elif weekday in [0,1,2,3,4] and hour == 0 and 55 <= minute <= 59:
        key = f"open_daily_{now.strftime('%Y%m%d')}"
        if key not in summary_sent:
            summary_sent[key] = True
            broadcast(
                f"⏰ <b>WTI открывается через 5 минут</b> (01:00 UTC / 04:00 МСК)\n"
                f"Следи за первыми свечами — они задают тон дня."
            )

    # Пн-Чт 21:55 UTC — за 5 мин до ежедневного закрытия
    elif weekday in [0,1,2,3] and hour == 21 and 55 <= minute <= 59:
        key = f"close_daily_{now.strftime('%Y%m%d')}"
        if key not in summary_sent:
            summary_sent[key] = True
            broadcast(
                f"⏰ <b>WTI закрывается через 5 минут</b> (22:00 UTC)\n"
                f"Открытие завтра в 01:00 UTC (04:00 МСК)."
            )

# ═══════════════════════════════════════════════════════════
#  ПАРСИНГ RSS
# ═══════════════════════════════════════════════════════════
def news_id(title: str, url: str) -> str:
    return hashlib.md5(f"{title}{url}".encode()).hexdigest()

def fetch_feed(feed: dict) -> list:
    try:
        parsed = feedparser.parse(feed["url"])
        items  = []
        for entry in parsed.entries[:15]:
            title   = entry.get("title",   "")
            url     = entry.get("link",    "")
            summary = entry.get("summary", "") or entry.get("description", "")
            items.append({
                "id":      news_id(title, url),
                "title":   title,
                "url":     url,
                "summary": summary[:300],
                "source":  feed["name"],
            })
        return items
    except Exception as e:
        return []

# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════
START_TIME = datetime.now().strftime("%d.%m %H:%M")

def main():
    global seen_news, subscribers

    print("╔══════════════════════════════════════════════════════╗")
    print("║   MARKET NEWS BOT — нефть / золото / крипта         ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    if not TG_TOKEN:
        print("  ❌ Заполни TG_TOKEN в news_bot.env или .env!"); return

    threading.Thread(target=handle_updates, daemon=True).start()
    print("  ✅ Telegram polling запущен")
    print(f"  📰 Источников: {len(RSS_FEEDS)}")
    print(f"  📋 Правил анализа: {len(RULES)}")
    print(f"  👥 Подписчиков: {len(subscribers)}\n")

    if subscribers:
        broadcast(
            f"🤖 <b>Market News Bot запущен</b>\n"
            f"Мониторю {len(RSS_FEEDS)} источников каждые {CHECK_INTERVAL} сек\n"
            f"Reuters • Bloomberg • AP • CNBC • OilPrice\n"
            f"FT • Truth Social • CoinTelegraph и другие\n\n"
            f"Присылаю важные новости по нефти, золоту и крипте."
        )

    iteration = 0

    while True:
        iteration += 1
        now_str   = datetime.now().strftime("%H:%M:%S")
        new_items = sent = 0

        check_market_schedule()

        print(f"  [{now_str}] Итер.{iteration} | подп.={len(subscribers)}", end="")

        for feed in RSS_FEEDS:
            items = fetch_feed(feed)
            for item in items:
                if item["id"] in seen_news:
                    continue
                seen_news.add(item["id"])
                new_items += 1

                analysis = analyze_by_rules(item["title"], item["summary"])
                if not analysis:
                    continue

                msg = format_alert(
                    item["title"], item["url"], item["source"], analysis
                )
                broadcast(msg)
                sent += 1

                print(f"\n  📰 {item['source']}: {item['title'][:55]}... "
                      f"→ {analysis['signal']}")

        save_json(SEEN_FILE, list(seen_news)[-5000:])
        print(f" | новых={new_items} отпр.={sent}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
