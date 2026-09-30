#!/usr/bin/env python3
"""
نسخه یک‌دوره‌ای ربات برای GitHub Actions
هر ۵ دقیقه یک‌بار اجرا می‌شود.
"""

import json
import os
from datetime import datetime
from typing import Optional
import asyncio

import requests
from telegram import Bot

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")

INITIAL_USDT = 100.0
DEX_FEE_PERCENT = 0.07
NETWORK_FEE_GRAM = 0.008
SLIPPAGE_PERCENT = 0.15
MIN_TRADE_USDT = 15.0
BUY_PERCENT = 0.60
STATE_FILE = "bot_state.json"


class PaperTrader:
    def __init__(self):
        self.usdt_balance = INITIAL_USDT
        self.gram_balance = 0.0
        self.entry_price = 0.0
        self.position_open = False
        self.trades = []
        self.start_time = datetime.now()
        self.prices = []
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
                self.prices = data.get("prices", [])
                self.start_time = datetime.fromisoformat(
                    data.get("start_time", datetime.now().isoformat())
                )
                print("وضعیت قبلی بارگذاری شد.")
            except Exception as e:
                print(f"خطا در بارگذاری: {e}")

    def save_state(self):
        data = {
            "usdt_balance": self.usdt_balance,
            "gram_balance": self.gram_balance,
            "entry_price": self.entry_price,
            "position_open": self.position_open,
            "trades": self.trades[-50:],
            "prices": self.prices[-30:],
            "start_time": self.start_time.isoformat(),
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_price(self) -> Optional[float]:
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": "the-open-network", "vs_currencies": "usd"}
            r = requests.get(url, params=params, timeout=12)
            r.raise_for_status()
            price = float(r.json()["the-open-network"]["usd"])
            print(f"قیمت فعلی: {price:.4f} USDT")
            return price
        except Exception as e:
            print(f"خطا در دریافت قیمت: {e}")
            return None

    def calculate_fees(self, amount_usdt: float) -> dict:
        return {
            "network_fee_gram": NETWORK_FEE_GRAM,
            "dex_fee_usdt": round(amount_usdt * (DEX_FEE_PERCENT / 100), 4),
            "slippage_usdt": round(amount_usdt * (SLIPPAGE_PERCENT / 100), 4),
            "total_extra_usdt": round(amount_usdt * ((DEX_FEE_PERCENT + SLIPPAGE_PERCENT) / 100), 4),
        }

    def buy(self, price: float, usdt_to_spend: float) -> bool:
        if self.position_open or usdt_to_spend > self.usdt_balance or usdt_to_spend < MIN_TRADE_USDT:
            return False
        fees = self.calculate_fees(usdt_to_spend)
        effective_usdt = usdt_to_spend - fees["total_extra_usdt"]
        gram_bought = (effective_usdt / price) - fees["network_fee_gram"]
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
        usdt_received = (gram_to_sell * price) - fees["total_extra_usdt"]
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

    def should_buy(self, price: float) -> bool:
        self.prices.append(price)
        if len(self.prices) > 30:
            self.prices.pop(0)
        if len(self.prices) < 5:
            return False
        avg = sum(self.prices[-5:]) / 5
        return price < avg * 0.97

    def should_sell(self, price: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        profit = (price - self.entry_price) / self.entry_price
        if profit >= 0.05:
            return 0.05
        if profit >= 0.02:
            return 0.02
        return 0.0


async def send_message(text: str):
    if not TELEGRAM_TOKEN or not CHANNEL_ID:
        print("Token یا Channel ID تنظیم نشده")
        print(text)
        return
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        await bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="HTML")
        print("پیام به کانال ارسال شد")
    except Exception as e:
        print(f"خطا در ارسال: {e}")


async def main():
    print("=" * 40)
    print("شروع دوره ترید (GitHub Actions)")
    print("=" * 40)

    if not TELEGRAM_TOKEN or not CHANNEL_ID:
        print("خطا: Secrets تنظیم نشده (TELEGRAM_TOKEN و CHANNEL_ID)")
        return

    trader = PaperTrader()
    price = trader.get_price()
    if price is None:
        print("نتوانست قیمت بگیرد")
        return

    print(f"موجودی: {trader.usdt_balance:.2f} USDT | {trader.gram_balance:.4f} GRAM")
    print(f"موقعیت باز: {trader.position_open}")

    traded = False

    if not trader.position_open and trader.should_buy(price):
        usdt_to_use = min(trader.usdt_balance * BUY_PERCENT, trader.usdt_balance - 5)
        if usdt_to_use >= MIN_TRADE_USDT and trader.buy(price, usdt_to_use):
            last = trader.trades[-1]
            msg = (
                f"🟢 <b>خرید انجام شد</b>\n"
                f"<i>(GitHub Actions)</i>\n\n"
                f"مقدار: <b>{last['gram']:.4f} GRAM</b>\n"
                f"قیمت: <b>{last['price']:.4f} USDT</b>\n"
                f"هزینه: {last['usdt']:.2f} USDT\n"
                f"کارمزد تقریبی: {last['fees']['total_extra_usdt']:.3f} USDT "
                f"+ {last['fees']['network_fee_gram']:.4f} GRAM\n"
                f"موجودی باقی‌مانده: {last['balance_usdt']:.2f} USDT"
            )
            await send_message(msg)
            traded = True
            print("خرید ثبت شد")

    elif trader.position_open:
        if trader.should_sell(price) > 0 and trader.sell(price):
            last = trader.trades[-1]
            msg = (
                f"🔴 <b>فروش انجام شد</b>\n"
                f"<i>(GitHub Actions)</i>\n\n"
                f"مقدار: <b>{last['gram']:.4f} GRAM</b>\n"
                f"قیمت فروش: <b>{last['price']:.4f} USDT</b>\n"
                f"دریافتی: {last['usdt']:.2f} USDT\n"
                f"سود: <b>{last['profit_usdt']:+.2f} USDT ({last['profit_pct']:+.2f}%)</b>\n"
                f"کارمزد تقریبی: {last['fees']['total_extra_usdt']:.3f} USDT\n"
                f"موجودی فعلی: {last['balance_usdt']:.2f} USDT"
            )
            await send_message(msg)
            traded = True
            print("فروش ثبت شد")

    trader.save_state()
    if not traded:
        print("در این دوره معامله‌ای انجام نشد.")
    print("دوره تمام شد.")


if __name__ == "__main__":
    asyncio.run(main())
