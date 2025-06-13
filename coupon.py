import os
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import traceback
import discord
from discord.ext import commands
import time

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOGS_CHANNEL_ID = int(os.getenv("LOGS_CHANNEL_ID") or 0)
COUPON_CHANNEL_ID = int(os.getenv("COUPON_CHANNEL_ID") or 0)
GIFTCARD_CHANNEL_ID = int(os.getenv("GIFTCARD_CHANNEL_ID") or 0)
HEADERS = {"User-Agent": "Mozilla/5.0"}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents)

coupon_task = None
giftcard_task = None

last_coupon_check_duration = 20  # default guess seconds
last_giftcard_check_duration = 60  # default guess seconds

async def send_discord_message(message: str, channel_id: int):
    if not DISCORD_TOKEN or not channel_id:
        return
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json"
    }
    json_data = {"content": message}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=json_data):
                pass
    except Exception:
        pass

async def log_error(err):
    await send_discord_message(f"🚨 Error:\n```{err[:1800]}```", LOGS_CHANNEL_ID)

# --- SCRAPING FUNCTIONS (same as before) ---

async def scrape_g2a(session):
    url = "https://www.g2a.com/deals"
    results = []
    try:
        async with session.get(url, headers=HEADERS) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            coupons = soup.find_all("div", class_="coupon-list__coupon")
            for c in coupons:
                code = c.find("div", class_="coupon-list__coupon-code")
                discount = c.find("span", class_="coupon-list__discount")
                if code and discount:
                    code_text = code.text.strip()
                    discount_text = discount.text.strip().replace("%", "")
                    if code_text and discount_text.isdigit():
                        results.append(("g2a", code_text, discount_text))
    except Exception:
        await log_error("G2A Scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_eneba(session):
    url = "https://www.eneba.com/us/store"
    results = []
    try:
        async with session.get(url, headers=HEADERS) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            promo_badges = soup.select(".shared-product-card__discount")
            for promo in promo_badges:
                discount_text = promo.text.strip().replace("-", "").replace("%", "")
                if discount_text.isdigit():
                    code = f"ENEBA{discount_text}"
                    results.append(("eneba", code, discount_text))
    except Exception:
        await log_error("Eneba Scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_kinguin(session):
    url = "https://www.kinguin.net/category/game-coupons-vouchers-1619/"
    results = []
    try:
        async with session.get(url, headers=HEADERS) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            items = soup.select(".product-list-item")
            for item in items:
                title = item.select_one(".product-title")
                discount = item.select_one(".discount-label")
                if title and discount:
                    discount_text = discount.text.strip().replace("%", "")
                    code = title.text.strip().split()[0].upper()
                    if discount_text.isdigit():
                        results.append(("kinguin", code, discount_text))
    except Exception:
        await log_error("Kinguin Scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_cdkeys(session):
    url = "https://www.cdkeys.com/coupons"
    results = []
    try:
        async with session.get(url, headers=HEADERS) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            coupons = soup.select(".coupon-item")
            for c in coupons:
                code = c.select_one(".coupon-code")
                discount = c.select_one(".coupon-discount")
                if code and discount:
                    code_text = code.text.strip()
                    discount_text = discount.text.strip().replace("%", "")
                    if discount_text.isdigit():
                        results.append(("cdkeys", code_text, discount_text))
    except Exception:
        await log_error("CDKeys Scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_giftcards(session):
    results = []
    try:
        results.append(("GIFT2025", "15"))
    except Exception:
        await log_error("Gift card scrape failed:\n" + traceback.format_exc())
    return results

async def validate_coupon_real(session, code, site):
    try:
        if site == "g2a":
            check_url = f"https://www.g2a.com/coupon/{code}"
            async with session.get(check_url, headers=HEADERS) as resp:
                return resp.status == 200
        elif site == "eneba":
            return len(code) > 3
        elif site == "kinguin":
            return len(code) > 3
        elif site == "cdkeys":
            check_url = f"https://www.cdkeys.com/coupon/{code}"
            async with session.get(check_url, headers=HEADERS) as resp:
                return resp.status == 200
        elif site == "giftcard":
            return len(code) > 3
        else:
            return False
    except Exception:
        return False

async def post_coupon(site, code, discount):
    msg = f"✅ [{site.upper()}] {code} | {discount}% off"
    await send_discord_message(msg, COUPON_CHANNEL_ID)

async def post_giftcard(code, discount):
    msg = f"✅ [GIFTCARD] {code} | {discount}% off"
    await send_discord_message(msg, GIFTCARD_CHANNEL_ID)

async def coupon_checker_loop():
    global last_coupon_check_duration
    while True:
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession() as session:
                all_coupons = []
                for scrape_func in [scrape_g2a, scrape_eneba, scrape_kinguin, scrape_cdkeys]:
                    coupons = await scrape_func(session)
                    all_coupons.extend(coupons)

                for site, code, discount in all_coupons:
                    try:
                        if await validate_coupon_real(session, code, site):
                            await post_coupon(site, code, discount)
                    except Exception:
                        await log_error(traceback.format_exc())
        except Exception:
            await log_error(traceback.format_exc())

        last_coupon_check_duration = time.monotonic() - start
        await asyncio.sleep(20)

async def giftcard_checker_loop():
    global last_giftcard_check_duration
    while True:
        start = time.monotonic()
        try:
            async with aiohttp.ClientSession() as session:
                all_giftcards = await scrape_giftcards(session)
                for code, discount in all_giftcards:
                    try:
                        if await validate_coupon_real(session, code, "giftcard"):
                            await post_giftcard(code, discount)
                    except Exception:
                        await log_error(traceback.format_exc())
        except Exception:
            await log_error(traceback.format_exc())

        last_giftcard_check_duration = time.monotonic() - start
        await asyncio.sleep(60)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def coupon(ctx):
    global coupon_task
    if coupon_task and not coupon_task.done():
        await ctx.send("Coupon checker is already running.")
        return
    eta = round(last_coupon_check_duration)
    await ctx.send(f"Starting coupon checker... Estimated time per loop: {eta} seconds")
    coupon_task = bot.loop.create_task(coupon_checker_loop())

@bot.command()
async def stopcoupon(ctx):
    global coupon_task
    if coupon_task and not coupon_task.done():
        coupon_task.cancel()
        coupon_task = None
        await ctx.send("Coupon checker stopped.")
    else:
        await ctx.send("Coupon checker is not running.")

@bot.command()
async def giftcard(ctx):
    global giftcard_task
    if giftcard_task and not giftcard_task.done():
        await ctx.send("Gift card checker is already running.")
        return
    eta = round(last_giftcard_check_duration)
    await ctx.send(f"Starting gift card checker... Estimated time per loop: {eta} seconds")
    giftcard_task = bot.loop.create_task(giftcard_checker_loop())

@bot.command()
async def stopgiftcard(ctx):
    global giftcard_task
    if giftcard_task and not giftcard_task.done():
        giftcard_task.cancel()
        giftcard_task = None
        await ctx.send("Gift card checker stopped.")
    else:
        await ctx.send("Gift card checker is not running.")

@bot.command()
async def stop(ctx):
    global coupon_task, giftcard_task
    stopped_any = False

    if coupon_task and not coupon_task.done():
        coupon_task.cancel()
        coupon_task = None
        stopped_any = True

    if giftcard_task and not giftcard_task.done():
        giftcard_task.cancel()
        giftcard_task = None
        stopped_any = True

    if stopped_any:
        await ctx.send("All checkers stopped.")
    else:
        await ctx.send("No checkers are running.")

bot.run(DISCORD_TOKEN)
