import logging, os, pytz
from datetime import datetime, time as dtime, timedelta

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from telegram.helpers import escape_markdown  # ← used everywhere we send Markdown V2

import database
from coingecko import (
    get_market_summary,
    get_top_gainers_losers,
    lookup_coin,
    get_coin_price,
    check_alerts,
)
from summarize import summarize_text

# ─────────────────── basics ───────────────────
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ────────────────── helpers ───────────────────
def _parse_time(text: str) -> str | None:
    """Validate HH:MM 24-h and return canonical 'HH:MM' or None."""
    try:
        h, m = map(int, text.split(":"))
        if 0 <= h < 24 and 0 <= m < 60:
            return f"{h:02d}:{m:02d}"
    except ValueError:
        pass
    return None


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает главное меню с inline кнопками"""
    keyboard = [
        [InlineKeyboardButton("📊 Сводка рынка", callback_data="summary")],
        [InlineKeyboardButton("📈 Топ растущие/падающие", callback_data="gainers")],
        [InlineKeyboardButton("💰 Поиск монеты", callback_data="price_search")],
        [InlineKeyboardButton("💼 Портфолио", callback_data="portfolio")],
        [InlineKeyboardButton("🔔 Уведомления", callback_data="alerts")],
        [InlineKeyboardButton("⏰ Настройка времени", callback_data="settime")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_time_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для выбора времени"""
    keyboard = [
        [InlineKeyboardButton("06:00", callback_data="time|06:00"),
         InlineKeyboardButton("09:00", callback_data="time|09:00"),
         InlineKeyboardButton("12:00", callback_data="time|12:00")],
        [InlineKeyboardButton("15:00", callback_data="time|15:00"),
         InlineKeyboardButton("18:00", callback_data="time|18:00"),
         InlineKeyboardButton("21:00", callback_data="time|21:00")],
        [InlineKeyboardButton("↩️ Назад", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_back_keyboard() -> InlineKeyboardMarkup:
    """Создает кнопку возврата в главное меню"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("↩️ Главное меню", callback_data="main_menu")]])


def get_alerts_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для управления уведомлениями"""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить уведомление", callback_data="add_alert")],
        [InlineKeyboardButton("📋 Мои уведомления", callback_data="list_alerts")],
        [InlineKeyboardButton("↩️ Главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


def get_portfolio_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру для управления портфолио"""
    keyboard = [
        [InlineKeyboardButton("📊 Обзор портфолио", callback_data="portfolio_overview")],
        [InlineKeyboardButton("📋 История транзакций", callback_data="transactions_list")],
        [InlineKeyboardButton("➕ Добавить покупку", callback_data="add_buy")],
        [InlineKeyboardButton("➖ Добавить продажу", callback_data="add_sell")],
        [InlineKeyboardButton("↩️ Главное меню", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(keyboard)


async def send_daily_summary(context: ContextTypes.DEFAULT_TYPE):
    uid = context.job.data["user_id"]
    if not (user := database.get_user(uid)):
        return
    raw_snapshot = get_market_summary()
    plain = summarize_text(raw_snapshot) + "\n\n_Not financial advice_"
    md = escape_markdown(plain, version=2)
    await context.bot.send_message(uid, md, parse_mode="MarkdownV2")


async def check_price_alerts(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет все активные уведомления и отправляет уведомления"""
    alerts = database.get_all_active_alerts()
    if not alerts:
        return
        
    triggered = check_alerts(alerts)
    
    for alert in triggered:
        user_id = alert["user_id"]
        coin = alert["coin"].upper()
        target = alert["target"]
        above = alert["above"]
        current_price = get_coin_price(alert["coin"])
        
        if current_price is None:
            continue
            
        # Формируем сообщение
        direction = "выше" if above else "ниже"
        msg = (
            f"🔔 *Уведомление о цене*\n\n"
            f"*{coin}* достиг цели!\n"
            f"Текущая цена: ${current_price:,.2f}\n"
            f"Цель: ${target:,.2f} ({direction})\n\n"
            f"_Уведомление автоматически удалено_"
        )
        
        try:
            await context.bot.send_message(
                user_id, 
                escape_markdown(msg, version=2), 
                parse_mode="MarkdownV2"
            )
            # Деактивируем уведомление
            database.deactivate_alert(alert["id"])
        except Exception as e:
            logger.error(f"Failed to send alert to {user_id}: {e}")


def schedule_user_summary(app, uid: int, tz: str, hhmm: str):
    """Create/replace the JobQueue task that delivers daily summary."""
    job_name = f"daily-{uid}"
    for j in app.job_queue.get_jobs_by_name(job_name):
        j.schedule_removal()

    hour, minute = map(int, hhmm.split(":"))
    user_tz = pytz.timezone(tz)
    now_loc = datetime.now(user_tz)
    target = user_tz.localize(datetime.combine(now_loc.date(), dtime(hour, minute)))
    if target <= now_loc:
        target += timedelta(days=1)

    delay = (target.astimezone(pytz.utc) - datetime.now(pytz.utc)).total_seconds()

    app.job_queue.run_repeating(
        send_daily_summary,
        interval=24 * 3600,
        first=delay,
        name=job_name,
        data={"user_id": uid},
        chat_id=uid,
    )


# ──────────────── command handlers ─────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    database.upsert_user(uid)
    msg = (
        "👋 Crypto Summary Bot\n"
        "Выберите нужную функцию:"
    )
    await update.message.reply_text(msg, reply_markup=get_main_menu_keyboard())


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_snapshot = get_market_summary()
    plain = summarize_text(raw_snapshot) + "\n\n_Not financial advice_"
    md = escape_markdown(plain, version=2)
    await update.message.reply_markdown_v2(md, reply_markup=get_back_keyboard())


TIMEZONES = ["UTC", "Europe/London", "US/Eastern", "Asia/Singapore"]


async def settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user = database.get_user(uid) or {}
    if context.args:
        hhmm = _parse_time(context.args[0])
        if not hhmm:
            await update.message.reply_text("Use /settime HH:MM (24-hour).")
            return
        database.upsert_user(uid, summary_at=hhmm)
        tz = user.get("tz", "UTC")
        schedule_user_summary(context.application, uid, tz, hhmm)
        await update.message.reply_text(f"✅ Time set to {hhmm} ({tz})")
        return

    if not user.get("tz"):
        kb = [[InlineKeyboardButton(z, callback_data=f"tz|{z}")] for z in TIMEZONES]
        await update.message.reply_text(
            "Choose your timezone:", reply_markup=InlineKeyboardMarkup(kb)
        )
    else:
        await update.message.reply_text(
            f"Current time: {user['summary_at']} ({user['tz']}). "
            "Send /settime HH:MM to change."
        )


async def tz_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, tz = q.data.split("|", 1)
    uid = q.from_user.id
    database.upsert_user(uid, tz=tz, summary_at="09:00")
    schedule_user_summary(context.application, uid, tz, "09:00")
    await q.edit_message_text(f"Timezone set to {tz}. Default time 09:00.")


def _fmt_coin_row(c: dict) -> str:
    ch = c["price_change_percentage_24h"] or 0
    arrow = "🔺" if ch >= 0 else "🔻"
    row_plain = f"*{c['symbol'].upper():<5}* {arrow} {ch:+.1f}% (${c['current_price']:,.2f})"
    return escape_markdown(row_plain, version=2)


async def gainers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ups, downs = get_top_gainers_losers()
    text = "*Top 24 h Gainers*\n" + "\n".join(_fmt_coin_row(c) for c in ups)
    text += "\n\n*Top 24 h Losers*\n" + "\n".join(_fmt_coin_row(c) for c in downs)
    await update.message.reply_markdown_v2(text + "\n\n_Not financial advice_", reply_markup=get_back_keyboard())


async def price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /price btc")
        return

    coin = lookup_coin(context.args[0])
    if not coin:
        await update.message.reply_text("Coin not found.")
        return

    plain = (
        f"*{coin['name']}* ({coin['symbol'].upper()})\n"
        f"Price: ${coin['current_price']:,.2f}\n"
        f"24 h: {coin['price_change_percentage_24h']:+.2f}%\n"
        f"Market cap: ${coin['market_cap']:,.0f}\n\n"
        "_Not financial advice_"
    )
    md = escape_markdown(plain, version=2)
    await update.message.reply_markdown_v2(md, reply_markup=get_back_keyboard())


# ──────────────── alert commands ─────────────
async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления уведомления: /alert btc > 50000"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "Использование: /alert <монета> <оператор> <цена>\n"
            "Примеры:\n"
            "/alert btc > 50000\n"
            "/alert eth < 3000"
        )
        return
    
    coin = context.args[0].lower()
    operator = context.args[1]
    try:
        target_price = float(context.args[2])
    except ValueError:
        await update.message.reply_text("Неверная цена. Используйте число.")
        return
    
    # Проверяем существование монеты
    if not get_coin_price(coin):
        await update.message.reply_text(f"Монета {coin.upper()} не найдена.")
        return
    
    # Определяем тип уведомления
    if operator in [">", ">=", "выше"]:
        above = True
    elif operator in ["<", "<=", "ниже"]:
        above = False
    else:
        await update.message.reply_text("Неверный оператор. Используйте >, <, выше, ниже")
        return
    
    uid = update.effective_user.id
    alert_id = database.add_alert(uid, coin, target_price, above)
    
    direction = "выше" if above else "ниже"
    msg = (
        f"✅ Уведомление добавлено!\n\n"
        f"Монета: {coin.upper()}\n"
        f"Условие: {direction} ${target_price:,.2f}\n"
        f"ID: {alert_id}"
    )
    
    await update.message.reply_text(msg, reply_markup=get_back_keyboard())


async def myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все уведомления пользователя"""
    uid = update.effective_user.id
    alerts = database.get_user_alerts(uid)
    
    if not alerts:
        await update.message.reply_text(
            "У вас нет активных уведомлений.\n"
            "Используйте /alert для добавления.",
            reply_markup=get_back_keyboard()
        )
        return
    
    msg = "*Ваши уведомления:*\n\n"
    for alert in alerts:
        direction = "выше" if alert["above"] else "ниже"
        current_price = get_coin_price(alert["coin"])
        price_info = f" (текущая: ${current_price:,.2f})" if current_price else ""
        
        msg += (
            f"*{alert['id']}.* {alert['coin'].upper()} {direction} "
            f"${alert['target']:,.2f}{price_info}\n"
        )
    
    msg += "\nДля удаления используйте: /delete <ID>"
    
    await update.message.reply_markdown_v2(
        escape_markdown(msg, version=2), 
        reply_markup=get_back_keyboard()
    )


async def delete_alert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет уведомление по ID"""
    if not context.args:
        await update.message.reply_text("Использование: /delete <ID>")
        return
    
    try:
        alert_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Неверный ID уведомления.")
        return
    
    uid = update.effective_user.id
    if database.delete_alert(alert_id, uid):
        await update.message.reply_text(f"✅ Уведомление {alert_id} удалено.")
    else:
        await update.message.reply_text("Уведомление не найдено или не принадлежит вам.")


# ──────────────── portfolio commands ─────────────
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления покупки: /buy btc 0.1 50000"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "Использование: /buy <монета> <количество> <цена>\n"
            "Примеры:\n"
            "/buy btc 0.1 50000\n"
            "/buy eth 2.5 3000"
        )
        return
    
    coin = context.args[0].lower()
    try:
        amount = float(context.args[1])
        price = float(context.args[2])
    except ValueError:
        await update.message.reply_text("Неверные числа. Используйте числа для количества и цены.")
        return
    
    if amount <= 0 or price <= 0:
        await update.message.reply_text("Количество и цена должны быть больше нуля.")
        return
    
    # Проверяем существование монеты
    if not get_coin_price(coin):
        await update.message.reply_text(f"Монета {coin.upper()} не найдена.")
        return
    
    uid = update.effective_user.id
    tx_id = database.add_transaction(uid, coin, "buy", amount, price)
    total = amount * price
    
    msg = (
        f"✅ Покупка добавлена!\n\n"
        f"Монета: {coin.upper()}\n"
        f"Количество: {amount}\n"
        f"Цена: ${price:,.2f}\n"
        f"Общая сумма: ${total:,.2f}\n"
        f"ID транзакции: {tx_id}"
    )
    
    await update.message.reply_text(msg, reply_markup=get_back_keyboard())


async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для добавления продажи: /sell btc 0.05 55000"""
    if len(context.args) < 3:
        await update.message.reply_text(
            "Использование: /sell <монета> <количество> <цена>\n"
            "Примеры:\n"
            "/sell btc 0.05 55000\n"
            "/sell eth 1.0 3200"
        )
        return
    
    coin = context.args[0].lower()
    try:
        amount = float(context.args[1])
        price = float(context.args[2])
    except ValueError:
        await update.message.reply_text("Неверные числа. Используйте числа для количества и цены.")
        return
    
    if amount <= 0 or price <= 0:
        await update.message.reply_text("Количество и цена должны быть больше нуля.")
        return
    
    # Проверяем существование монеты
    if not get_coin_price(coin):
        await update.message.reply_text(f"Монета {coin.upper()} не найдена.")
        return
    
    uid = update.effective_user.id
    
    # Проверяем, есть ли достаточно монет для продажи
    portfolio = database.get_user_portfolio(uid)
    coin_position = next((pos for pos in portfolio if pos["coin"] == coin), None)
    
    if not coin_position or coin_position["amount"] < amount:
        await update.message.reply_text(
            f"Недостаточно {coin.upper()} для продажи.\n"
            f"Доступно: {coin_position['amount'] if coin_position else 0}"
        )
        return
    
    tx_id = database.add_transaction(uid, coin, "sell", amount, price)
    total = amount * price
    
    msg = (
        f"✅ Продажа добавлена!\n\n"
        f"Монета: {coin.upper()}\n"
        f"Количество: {amount}\n"
        f"Цена: ${price:,.2f}\n"
        f"Общая сумма: ${total:,.2f}\n"
        f"ID транзакции: {tx_id}"
    )
    
    await update.message.reply_text(msg, reply_markup=get_back_keyboard())


async def portfolio_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает портфолио пользователя"""
    uid = update.effective_user.id
    summary = database.get_portfolio_summary(uid, get_coin_price)
    
    if summary["positions"] == 0:
        await update.message.reply_text(
            "Ваше портфолио пусто.\n"
            "Используйте /buy для добавления покупок.",
            reply_markup=get_back_keyboard()
        )
        return
    
    msg = "*💼 Ваше портфолио:*\n\n"
    
    # Общая сводка
    pnl_emoji = "🔺" if summary["total_pnl"] >= 0 else "🔻"
    msg += (
        f"*Общая стоимость:* ${summary['total_current']:,.2f}\n"
        f"*Инвестировано:* ${summary['total_invested']:,.2f}\n"
        f"*P&L:* {pnl_emoji} ${summary['total_pnl']:+,.2f} ({summary['total_pnl_percent']:+.1f}%)\n"
        f"*Позиций:* {summary['positions']}\n\n"
    )
    
    # Детали по позициям
    msg += "*Позиции:*\n"
    for pos in summary["positions_detail"]:
        pnl_emoji = "🔺" if pos["pnl"] >= 0 else "🔻"
        msg += (
            f"*{pos['coin'].upper()}*: {pos['amount']} × ${pos['current_price']:,.2f} = "
            f"${pos['current_value']:,.2f}\n"
            f"  P&L: {pnl_emoji} ${pos['pnl']:+,.2f} ({pos['pnl_percent']:+.1f}%)\n\n"
        )
    
    await update.message.reply_markdown_v2(
        escape_markdown(msg, version=2), 
        reply_markup=get_back_keyboard()
    )


async def transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает историю транзакций"""
    uid = update.effective_user.id
    txs = database.get_user_transactions(uid, 10)
    
    if not txs:
        await update.message.reply_text(
            "У вас нет транзакций.\n"
            "Используйте /buy или /sell для добавления.",
            reply_markup=get_back_keyboard()
        )
        return
    
    msg = "*📋 Последние транзакции:*\n\n"
    
    for tx in txs:
        tx_type = "🟢 Покупка" if tx["type"] == "buy" else "🔴 Продажа"
        date = datetime.fromisoformat(tx["date"].replace('Z', '+00:00')).strftime("%d.%m %H:%M")
        msg += (
            f"*{tx['id']}.* {tx_type} {tx['coin'].upper()}\n"
            f"  {tx['amount']} × ${tx['price']:,.2f} = ${tx['total']:,.2f}\n"
            f"  {date}\n\n"
        )
    
    await update.message.reply_markdown_v2(
        escape_markdown(msg, version=2), 
        reply_markup=get_back_keyboard()
    )


# ──────────────── callback handlers ─────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик всех callback запросов от inline кнопок"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "main_menu":
        msg = "👋 Crypto Summary Bot\nВыберите нужную функцию:"
        await query.edit_message_text(msg, reply_markup=get_main_menu_keyboard())
        
    elif data == "summary":
        raw_snapshot = get_market_summary()
        plain = summarize_text(raw_snapshot) + "\n\n_Not financial advice_"
        md = escape_markdown(plain, version=2)
        await query.edit_message_text(md, parse_mode="MarkdownV2", reply_markup=get_back_keyboard())
        
    elif data == "gainers":
        ups, downs = get_top_gainers_losers()
        text = "*Top 24 h Gainers*\n" + "\n".join(_fmt_coin_row(c) for c in ups)
        text += "\n\n*Top 24 h Losers*\n" + "\n".join(_fmt_coin_row(c) for c in downs)
        await query.edit_message_text(text + "\n\n_Not financial advice_", parse_mode="MarkdownV2", reply_markup=get_back_keyboard())
        
    elif data == "price_search":
        msg = (
            "💰 Поиск монеты\n\n"
            "Введите символ монеты (например: btc, eth, ada)\n"
            "Используйте команду: /price <символ>"
        )
        await query.edit_message_text(msg, reply_markup=get_back_keyboard())
        
    elif data == "alerts":
        msg = (
            "🔔 Управление уведомлениями\n\n"
            "Здесь вы можете настроить уведомления о ценах криптовалют."
        )
        await query.edit_message_text(msg, reply_markup=get_alerts_keyboard())
        
    elif data == "add_alert":
        msg = (
            "➕ Добавить уведомление\n\n"
            "Используйте команду:\n"
            "`/alert <монета> <оператор> <цена>`\n\n"
            "Примеры:\n"
            "• `/alert btc > 50000` - когда BTC будет выше $50,000\n"
            "• `/alert eth < 3000` - когда ETH будет ниже $3,000\n\n"
            "Операторы: >, <, выше, ниже"
        )
        await query.edit_message_text(msg, reply_markup=get_back_keyboard())
        
    elif data == "list_alerts":
        uid = query.from_user.id
        alerts = database.get_user_alerts(uid)
        
        if not alerts:
            msg = (
                "📋 Ваши уведомления\n\n"
                "У вас нет активных уведомлений.\n"
                "Используйте команду `/alert` для добавления."
            )
        else:
            msg = "*📋 Ваши уведомления:*\n\n"
            for alert in alerts:
                direction = "выше" if alert["above"] else "ниже"
                current_price = get_coin_price(alert["coin"])
                price_info = f" (текущая: ${current_price:,.2f})" if current_price else ""
                
                msg += (
                    f"*{alert['id']}.* {alert['coin'].upper()} {direction} "
                    f"${alert['target']:,.2f}{price_info}\n"
                )
            
            msg += "\nДля удаления используйте: `/delete <ID>`"
        
        await query.edit_message_text(
            escape_markdown(msg, version=2), 
            parse_mode="MarkdownV2",
            reply_markup=get_back_keyboard()
        )
        
    elif data == "portfolio":
        msg = (
            "💼 Управление портфолио\n\n"
            "Здесь вы можете отслеживать свои криптовалютные активы."
        )
        await query.edit_message_text(msg, reply_markup=get_portfolio_keyboard())
        
    elif data == "portfolio_overview":
        uid = query.from_user.id
        summary = database.get_portfolio_summary(uid, get_coin_price)
        
        if summary["positions"] == 0:
            msg = (
                "💼 Ваше портфолио\n\n"
                "Ваше портфолио пусто.\n"
                "Используйте команду `/buy` для добавления покупок."
            )
        else:
            pnl_emoji = "🔺" if summary["total_pnl"] >= 0 else "🔻"
            msg = (
                f"💼 *Ваше портфолио*\n\n"
                f"*Общая стоимость:* ${summary['total_current']:,.2f}\n"
                f"*Инвестировано:* ${summary['total_invested']:,.2f}\n"
                f"*P&L:* {pnl_emoji} ${summary['total_pnl']:+,.2f} ({summary['total_pnl_percent']:+.1f}%)\n"
                f"*Позиций:* {summary['positions']}\n\n"
                f"Используйте команду `/portfolio` для детального просмотра."
            )
        
        await query.edit_message_text(
            escape_markdown(msg, version=2), 
            parse_mode="MarkdownV2",
            reply_markup=get_back_keyboard()
        )
        
    elif data == "transactions_list":
        uid = query.from_user.id
        txs = database.get_user_transactions(uid, 10)
        
        if not txs:
            msg = (
                "📋 История транзакций\n\n"
                "У вас нет транзакций.\n"
                "Используйте команды `/buy` или `/sell` для добавления."
            )
        else:
            msg = "*📋 Последние транзакции:*\n\n"
            
            for tx in txs:
                tx_type = "🟢 Покупка" if tx["type"] == "buy" else "🔴 Продажа"
                date = datetime.fromisoformat(tx["date"].replace('Z', '+00:00')).strftime("%d.%m %H:%M")
                msg += (
                    f"*{tx['id']}.* {tx_type} {tx['coin'].upper()}\n"
                    f"  {tx['amount']} × ${tx['price']:,.2f} = ${tx['total']:,.2f}\n"
                    f"  {date}\n\n"
                )
        
        await query.edit_message_text(
            escape_markdown(msg, version=2), 
            parse_mode="MarkdownV2",
            reply_markup=get_back_keyboard()
        )
        
    elif data == "add_buy":
        msg = (
            "➕ Добавить покупку\n\n"
            "Используйте команду:\n"
            "`/buy <монета> <количество> <цена>`\n\n"
            "Примеры:\n"
            "• `/buy btc 0.1 50000` - купил 0.1 BTC по $50,000\n"
            "• `/buy eth 2.5 3000` - купил 2.5 ETH по $3,000\n\n"
            "Монета: символ (btc, eth, ada, etc.)\n"
            "Количество: сколько купили\n"
            "Цена: цена за единицу в USD"
        )
        await query.edit_message_text(msg, reply_markup=get_back_keyboard())
        
    elif data == "add_sell":
        msg = (
            "➖ Добавить продажу\n\n"
            "Используйте команду:\n"
            "`/sell <монета> <количество> <цена>`\n\n"
            "Примеры:\n"
            "• `/sell btc 0.05 55000` - продал 0.05 BTC по $55,000\n"
            "• `/sell eth 1.0 3200` - продал 1.0 ETH по $3,200\n\n"
            "Монета: символ (btc, eth, ada, etc.)\n"
            "Количество: сколько продали\n"
            "Цена: цена за единицу в USD"
        )
        await query.edit_message_text(msg, reply_markup=get_back_keyboard())
        
    elif data == "settime":
        uid = query.from_user.id
        user = database.get_user(uid) or {}
        
        if not user.get("tz"):
            kb = [[InlineKeyboardButton(z, callback_data=f"tz|{z}")] for z in TIMEZONES]
            kb.append([InlineKeyboardButton("↩️ Назад", callback_data="main_menu")])
            await query.edit_message_text(
                "Выберите ваш часовой пояс:", 
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await query.edit_message_text(
                f"Текущее время: {user['summary_at']} ({user['tz']})\n\n"
                "Выберите новое время:",
                reply_markup=get_time_keyboard()
            )
            
    elif data == "help":
        msg = (
            "ℹ️ Помощь\n\n"
            "📊 **Сводка рынка** - AI-анализ текущего состояния рынка\n"
            "📈 **Топ растущие/падающие** - лучшие и худшие монеты за 24 часа\n"
            "💰 **Поиск монеты** - информация о конкретной монете\n"
            "💼 **Портфолио** - управление криптовалютным портфолио\n"
            "🔔 **Уведомления** - настройка уведомлений о ценах\n"
            "⏰ **Настройка времени** - установка времени ежедневных сводок\n\n"
            "Команды:\n"
            "• /start - главное меню\n"
            "• /summary - сводка рынка\n"
            "• /gainers - топ монет\n"
            "• /price <монета> - цена монеты\n"
            "• /buy <монета> <количество> <цена> - добавить покупку\n"
            "• /sell <монета> <количество> <цена> - добавить продажу\n"
            "• /portfolio - обзор портфолио\n"
            "• /transactions - история транзакций\n"
            "• /alert <монета> <оператор> <цена> - добавить уведомление\n"
            "• /myalerts - мои уведомления\n"
            "• /delete <ID> - удалить уведомление\n"
            "• /settime HH:MM - время сводок\n\n"
            "_Not financial advice_"
        )
        await query.edit_message_text(msg, reply_markup=get_back_keyboard())
        
    elif data.startswith("tz|"):
        _, tz = data.split("|", 1)
        uid = query.from_user.id
        database.upsert_user(uid, tz=tz, summary_at="09:00")
        schedule_user_summary(context.application, uid, tz, "09:00")
        await query.edit_message_text(
            f"Часовой пояс установлен: {tz}\nВремя по умолчанию: 09:00\n\n"
            "Выберите время ежедневных сводок:",
            reply_markup=get_time_keyboard()
        )
        
    elif data.startswith("time|"):
        _, time_str = data.split("|", 1)
        uid = query.from_user.id
        user = database.get_user(uid) or {}
        tz = user.get("tz", "UTC")
        
        database.upsert_user(uid, summary_at=time_str)
        schedule_user_summary(context.application, uid, tz, time_str)
        
        await query.edit_message_text(
            f"✅ Время установлено: {time_str} ({tz})\n\n"
            "Ежедневные сводки будут приходить в указанное время.",
            reply_markup=get_back_keyboard()
        )


# ─────────────────── bootstrap ──────────────────
def start_bot():
    database.init_db()

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("summary", summary))
    app.add_handler(CommandHandler("settime", settime))
    app.add_handler(CommandHandler("gainers", gainers))
    app.add_handler(CommandHandler("price",   price))
    app.add_handler(CommandHandler("alert",   alert))
    app.add_handler(CommandHandler("myalerts", myalerts))
    app.add_handler(CommandHandler("delete",  delete_alert_cmd))
    app.add_handler(CommandHandler("buy",     buy))
    app.add_handler(CommandHandler("sell",    sell))
    app.add_handler(CommandHandler("portfolio", portfolio_cmd))
    app.add_handler(CommandHandler("transactions", transactions))
    app.add_handler(CallbackQueryHandler(handle_callback))

    # Запускаем проверку уведомлений каждые 5 минут
    app.job_queue.run_repeating(check_price_alerts, interval=300)

    # Reschedule summaries on restart
    for u in database.all_users():
        schedule_user_summary(app, u["user_id"], u["tz"], u["summary_at"])

    logger.info("🤖 Bot live")
    app.run_polling()