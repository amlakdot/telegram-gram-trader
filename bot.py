#!/usr/bin/env python3
"""
Telegram Paper Trading Bot - GRAM / USDT
شبیه‌سازی ترید بین GRAM (تون‌کوین سابق) و USDT روی STON.fi
بدون پول واقعی - فقط کاغذی (Paper Trading)
"""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

# ================== تنظیمات ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

INITIAL_USDT = 100.0
DEX_FEE_PERCENT = 0.07          # کارمزد DEX حدود ۰.۰۷٪ (STON.fi)
NETWORK_FEE_GRAM = 0.008        # میانگین کارمزد شبکه از تراکنش‌های واقعی
SLIPPAGE_PERCENT = 0.15         # لغزش تقریبی
PROFIT_TARGETS = [0.02, 0.05]   # اهداف سود ۲٪ و ۵٪
CHECK_INTERVAL = 60             # چک قیمت هر ۶۰ ثانیه
MIN_TRADE_USDT = 15.0           # حداقل اندازه معامله
BUY_PERCENT = 0.60              # درصد سرمایه برای هر خرید

STATE_FILE = "bot_state.json"

# ================== کلاس شبیه‌ساز ترید ==================
class PaperTrader:
    def __init__(self):
        self.usdt_balance = INITIAL_USDT
        self.gram_balance = 0.0
        self.entry_price = 0.0
        self.position_open = False
        self.trades: list = []
        self.start_time = datetime.now()
        self.load_state()

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.usdt_balance = data.get("usdt_balance", INITIAL_USDT)
                self.gram_balance = data.get("gram_balance", 0.0)
                self.entry_price = data.get("entry_price", 0.0)
                self.position_open = data.get("position_open", False)
                self.trades = data.get("trades", [])
                self.start_time = datetime.fromisoformat(
                    data.get("start_time", datetime.now().isoformat())
                )
            except Exception as e:
                print(f"خطا در بارگذاری وضعیت: {e}")

    def save_state(self):
        data = {
            "usdt_balance": self.usdt_balance,
            "gram_balance": self.gram_balance,
            "entry_price": self.entry_price,
            "position_open": self.position_open,
            "trades": self.trades,
            "start_time": self.start_time.isoformat(),
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_price(self) -> Optional[float]:
        """قیمت لحظه‌ای GRAM/USDT از CoinGecko"""
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": "the-open-network", "vs_currencies": "usd"}
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return float(r.json()["the-open-network"]["usd"])
        except Exception as e:
            print(f"خطا در دریافت قیمت: {e}")
            return None

    def calculate_fees(self, amount_usdt: float) -> dict:
        """محاسبه کارمزدها بر اساس تراکنش‌های واقعی STON.fi"""
        network_fee_gram = NETWORK_FEE_GRAM
        dex_fee_usdt = amount_usdt * (DEX_FEE_PERCENT / 100)
        slippage_usdt = amount_usdt * (SLIPPAGE_PERCENT / 100)
        total_extra_usdt = dex_fee_usdt + slippage_usdt
        return {
            "network_fee_gram": network_fee_gram,
            "dex_fee_usdt": round(dex_fee_usdt, 4),
            "slippage_usdt": round(slippage_usdt, 4),
            "total_extra_usdt": round(total_extra_usdt, 4),
        }

    def buy(self, price: float, usdt_to_spend: float) -> bool:
        if self.position_open or usdt_to_spend > self.usdt_balance or usdt_to_spend < MIN_TRADE_USDT:
            return False

        fees = self.calculate_fees(usdt_to_spend)
        effective_usdt = usdt_to_spend - fees["total_extra_usdt"]
        gram_bought = effective_usdt / price
        gram_bought -= fees["network_fee_gram"]

        if gram_bought <= 0:
            return False

        self.usdt_balance -= usdt_to_spend
        self.gram_balance += gram_bought
        self.entry_price = price
        self.position_open = True

        trade = {
            "type": "BUY",
            "time": datetime.now().isoformat(),
            "price": round(price, 6),
            "gram": round(gram_bought, 6),
            "usdt": round(usdt_to_spend, 2),
            "fees": fees,
            "balance_usdt": round(self.usdt_balance, 2),
            "balance_gram": round(self.gram_balance, 6),
        }
        self.trades.append(trade)
        self.save_state()
        return True

    def sell(self, price: float) -> bool:
        if not self.position_open or self.gram_balance <= 0:
            return False

        fees = self.calculate_fees(self.gram_balance * price)
        gram_to_sell = self.gram_balance - fees["network_fee_gram"]
        usdt_received = gram_to_sell * price - fees["total_extra_usdt"]

        profit_pct = ((price - self.entry_price) / self.entry_price) * 100
        cost_basis = self.gram_balance * self.entry_price
        profit_usdt = usdt_received - cost_basis

        self.usdt_balance += usdt_received
        self.gram_balance = 0.0
        self.position_open = False
        old_entry = self.entry_price
        self.entry_price = 0.0

        trade = {
            "type": "SELL",
            "time": datetime.now().isoformat(),
            "price": round(price, 6),
            "gram": round(gram_to_sell, 6),
            "usdt": round(usdt_received, 2),
            "entry_price": round(old_entry, 6),
            "profit_pct": round(profit_pct, 2),
            "profit_usdt": round(profit_usdt, 2),
            "fees": fees,
            "balance_usdt": round(self.usdt_balance, 2),
            "balance_gram": 0.0,
        }
        self.trades.append(trade)
        self.save_state()
        return True

    def get_portfolio_value(self, price: float) -> float:
        return self.usdt_balance + (self.gram_balance * price)

    def get_report(self, price: float) -> str:
        total_value = self.get_portfolio_value(price)
        profit = total_value - INITIAL_USDT
        profit_pct = (profit / INITIAL_USDT) * 100 if INITIAL_USDT else 0
        days = max((datetime.now() - self.start_time).days, 1)
        buy_count = sum(1 for t in self.trades if t["type"] == "BUY")
        sell_count = sum(1 for t in self.trades if t["type"] == "SELL")

        return (
            f"📊 <b>گزارش شبیه‌سازی ترید GRAM/USDT</b>\n\n"
            f"💰 سرمایه اولیه: <b>{INITIAL_USDT:.2f} USDT</b>\n"
            f"📈 ارزش فعلی: <b>{total_value:.2f} USDT</b>\n"
            f"{'🟢' if profit >= 0 else '🔴'} سود/زیان: <b>{profit:+.2f} USDT ({profit_pct:+.2f}%)</b>\n\n"
            f"🔢 تعداد خرید: {buy_count} | فروش: {sell_count}\n"
            f"📅 روزهای گذشته: {days}\n"
            f"💵 موجودی USDT: {self.usdt_balance:.2f}\n"
            f"🪙 موجودی GRAM: {self.gram_balance:.4f}"
        )


# ================== استراتژی ساده ==================
class SimpleStrategy:
    def __init__(self, lookback: int = 5):
        self.prices: list[float] = []
        self.lookback = lookback

    def update(self, price: float):
        self.prices.append(price)
        if len(self.prices) > 30:
            self.prices.pop(0)

    def should_buy(self, price: float) -> bool:
        if len(self.prices) < self.lookback:
            return False
        avg = sum(self.prices[-self.lookback :]) / self.lookback
        # خرید وقتی قیمت حدود ۳٪ زیر میانگین کوتاه‌مدت باشد
        return price < avg * 0.97

    def should_sell(self, price: float, entry: float) -> float:
        if entry <= 0:
            return 0.0
        profit = (price - entry) / entry
        if profit >= 0.05:
            return 0.05
        if profit >= 0.02:
            return 0.02
        return 0.0


# ================== ربات تلگرام ==================
trader = PaperTrader()
strategy = SimpleStrategy()


async def send_to_channel(text: str):
    if not CHANNEL_ID:
        print("CHANNEL_ID تنظیم نشده")
        return
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"خطا در ارسال به کانال: {e}")


async def trading_loop(context: ContextTypes.DEFAULT_TYPE):
    print("حلقه ترید شروع شد...")
    while True:
        try:
            price = trader.get_price()
            if price is None:
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            strategy.update(price)

            # خرید
            if not trader.position_open and strategy.should_buy(price):
                usdt_to_use = min(trader.usdt_balance * BUY_PERCENT, trader.usdt_balance - 5)
                if usdt_to_use >= MIN_TRADE_USDT:
                    if trader.buy(price, usdt_to_use):
                        last = trader.trades[-1]
                        msg = (
                            f"🟢 <b>خرید انجام شد</b>\n\n"
                            f"مقدار: <b>{last['gram']:.4f} GRAM</b>\n"
                            f"قیمت: <b>{last['price']:.4f} USDT</b>\n"
                            f"هزینه: {last['usdt']:.2f} USDT\n"
                            f"کارمزد تقریبی: {last['fees']['total_extra_usdt']:.3f} USDT "
                            f"+ {last['fees']['network_fee_gram']:.4f} GRAM\n"
                            f"موجودی باقی‌مانده: {last['balance_usdt']:.2f} USDT"
                        )
                        await send_to_channel(msg)
                        print(f"BUY @ {price:.4f}")

            # فروش
            elif trader.position_open:
                target = strategy.should_sell(price, trader.entry_price)
                if target > 0:
                    if trader.sell(price):
                        last = trader.trades[-1]
                        msg = (
                            f"🔴 <b>فروش انجام شد</b>\n\n"
                            f"مقدار: <b>{last['gram']:.4f} GRAM</b>\n"
                            f"قیمت فروش: <b>{last['price']:.4f} USDT</b>\n"
                            f"دریافتی: {last['usdt']:.2f} USDT\n"
                            f"سود: <b>{last['profit_usdt']:+.2f} USDT ({last['profit_pct']:+.2f}%)</b>\n"
                            f"کارمزد تقریبی: {last['fees']['total_extra_usdt']:.3f} USDT\n"
                            f"موجودی فعلی: {last['balance_usdt']:.2f} USDT"
                        )
                        await send_to_channel(msg)
                        print(f"SELL @ {price:.4f} | profit {last['profit_pct']}%")

            # گزارش دوره‌ای هر ۶ ساعت
            if int(time.time()) % 21600 < CHECK_INTERVAL:
                report = trader.get_report(price)
                await send_to_channel(report)

        except Exception as e:
            print(f"خطا در حلقه ترید: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 ربات تریدر شبیه‌سازی GRAM/USDT فعال است.\n\n"
        "هر معامله به صورت خودکار در کانال پست می‌شود.\n\n"
        "دستورات:\n"
        "/status - وضعیت فعلی\n"
        "/report - گزارش سود/زیان\n"
        "/trades - آخرین معاملات"
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = trader.get_price() or 0.0
    value = trader.get_portfolio_value(price)
    pos = "باز 🟢" if trader.position_open else "بسته ⚪"
    text = (
        f"📊 <b>وضعیت فعلی</b>\n\n"
        f"قیمت GRAM: <b>{price:.4f} USDT</b>\n"
        f"موجودی USDT: {trader.usdt_balance:.2f}\n"
        f"موجودی GRAM: {trader.gram_balance:.4f}\n"
        f"موقعیت: {pos}\n"
        f"ارزش کل پورتفوی: <b>{value:.2f} USDT</b>"
    )
    if trader.position_open:
        unrealized = ((price - trader.entry_price) / trader.entry_price) * 100
        text += f"\nسود/زیان باز: {unrealized:+.2f}%"
    await update.message.reply_text(text, parse_mode="HTML")


async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    price = trader.get_price() or 0.0
    await update.message.reply_text(trader.get_report(price), parse_mode="HTML")


async def trades_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not trader.trades:
        await update.message.reply_text("هنوز معامله‌ای ثبت نشده.")
        return
    lines = ["📜 <b>آخرین معاملات:</b>\n"]
    for t in trader.trades[-8:]:
        emoji = "🟢" if t["type"] == "BUY" else "🔴"
        if t["type"] == "BUY":
            lines.append(
                f"{emoji} خرید {t['gram']:.3f} GRAM @ {t['price']:.4f} "
                f"({t['usdt']:.1f} USDT)"
            )
        else:
            lines.append(
                f"{emoji} فروش {t['gram']:.3f} GRAM @ {t['price']:.4f} "
                f"| سود {t.get('profit_pct', 0):+.1f}%"
            )
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


def main():
    if not TELEGRAM_TOKEN:
        raise SystemExit("❌ TELEGRAM_TOKEN در فایل .env تنظیم نشده است.")
    if not CHANNEL_ID:
        print("⚠️  CHANNEL_ID تنظیم نشده - پیام‌ها فقط در کنسول چاپ می‌شوند.")

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("report", report_cmd))
    app.add_handler(CommandHandler("trades", trades_cmd))

    # شروع حلقه ترید
    if app.job_queue:
        app.job_queue.run_once(lambda ctx: asyncio.create_task(trading_loop(ctx)), when=3)
    else:
        print("JobQueue در دسترس نیست - حلقه ترید دستی شروع می‌شود")

    print("✅ ربات شروع به کار کرد...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
