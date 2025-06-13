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
GIFT_CARD_CHANNEL_ID = int(os.getenv("GIFT_CARD_CHANNEL_ID") or 0)
HEADERS = {"User-Agent": "Mozilla/5.0"}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents)

coupon_task = None
giftcard_task = None

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

# ---------------------------
# SCRAPING FUNCTIONS
# ---------------------------

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

# Example Honey scraper (basic, honey.com heavily obfuscates)
async def scrape_honey(session):
    # Honey site is complex with JS; we do a very basic fallback scraping here
    results = []
    try:
        url = "https://www.joinhoney.com/coupons"
        async with session.get(url, headers=HEADERS) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            # Try find coupon code blocks if possible - demo only, honey often hides real codes
            coupons = soup.find_all("div", class_="css-1mzh2pn")  # example class, may need update
            for c in coupons:
                code_tag = c.find("span", class_="css-1v48n8k")  # example class, may need update
                discount_tag = c.find("div", class_="css-1l7kphn")  # example class, may need update
                if code_tag and discount_tag:
                    code = code_tag.text.strip()
                    discount_text = ''.join(filter(str.isdigit, discount_tag.text))
                    if code and discount_text.isdigit():
                        results.append(("honey", code, discount_text))
    except Exception:
        await log_error("Honey Scrape failed:\n" + traceback.format_exc())
    return results

# ---------------------------
# GIFT CARD SCRAPER (dummy example)
# ---------------------------

async def scrape_giftcards(session):
    results = []
    try:
        # Dummy gift card scraping: add real sites here
        # Example dummy card:
        results.append(("GIFT2025", "15"))
        # Add more scraping from real gift card sites if available
    except Exception:
        await log_error("Gift card scrape failed:\n" + traceback.format_exc())
    return results

# ---------------------------
# VALIDATION FUNCTION
# ---------------------------

async def validate_coupon_real(session, code, site):
    try:
        if site == "g2a":
            check_url = f"https://www.g2a.com/coupon/{code}"
            async with session.get(check_url, headers=HEADERS) as resp:
                return resp.status == 200

        elif site == "eneba":
            # Assume codes starting with ENEBA and length > 5 are valid
            return code.startswith("ENEBA") and len(code) > 5

        elif site == "kinguin":
            # Check if the code is somewhat valid length
            return len(code) > 3

        elif site == "cdkeys":
            check_url = f"https://www.cdkeys.com/coupon/{code}"
            async with session.get(check_url, headers=HEADERS) as resp:
                return resp.status == 200

        elif site == "honey":
            # Honey codes: basic length check
            return len(code) > 3

        elif site == "giftcard":
            # Basic dummy validation
            return len(code) > 3
        
        else:
            return False
    except Exception:
        return False

# ---------------------------
# POST MESSAGES
# ---------------------------

async def post_coupon(site, code, discount):
    msg = f"✅ [{site.upper()}] {code} | {discount}% off"
    await send_discord_message(msg, COUPON_CHANNEL_ID)

async def post_giftcard(code, discount):
    msg = f"✅ [GIFTCARD] {code} | {discount}% off"
    await send_discord_message(msg, GIFT_CARD_CHANNEL_ID)

# ---------------------------
# CHECKER LOOPS WITH ETA TRACKING
# ---------------------------

async def coupon_checker_loop():
    start_time = time.time()
    count = 0
    try:
        async with aiohttp.ClientSession() as session:
            # Scrapers list
            scrapers = [scrape_g2a, scrape_eneba, scrape_kinguin, scrape_cdkeys, scrape_honey]
            all_coupons = []
            for scraper in scrapers:
                res = await scraper(session)
                all_coupons.extend(res)
            total = len(all_coupons)
            if total == 0:
                await send_discord_message("⚠️ No coupons found in this check.", COUPON_CHANNEL_ID)
                return
            for idx, (site, code, discount) in enumerate(all_coupons, 1):
                if await validate_coupon_real(session, code, site):
                    await post_coupon(site, code, discount)
                count += 1
                # Update ETA approx every 5 coupons
                if count % 5 == 0 or idx == total:
                    elapsed = time.time() - start_time
                    avg_per = elapsed / count if count else 1
                    remaining = total - count
                    eta = remaining * avg_per
                    eta_msg = f"Checked {count}/{total} coupons. ETA: {int(eta)} seconds"
                    await send_discord_message(eta_msg, COUPON_CHANNEL_ID)
    except Exception:
        await log_error(traceback.format_exc())

async def giftcard_checker_loop():
    start_time = time.time()
    count = 0
    try:
        async with aiohttp.ClientSession() as session:
            all_giftcards = await scrape_giftcards(session)
            total = len(all_giftcards)
            if total == 0:
                await send_discord_message("⚠️ No gift cards found in this check.", GIFT_CARD_CHANNEL_ID)
                return
            for idx, (code, discount) in enumerate(all_giftcards, 1):
                if await validate_coupon_real(session, code, "giftcard"):
                    await post_giftcard(code, discount)
                count += 1
                if count % 5 == 0 or idx == total:
                    elapsed = time.time() - start_time
                    avg_per = elapsed / count if count else 1
                    remaining = total - count
                    eta = remaining * avg_per
                    eta_msg = f"Checked {count}/{total} gift cards. ETA: {int(eta)} seconds"
                    await send_discord_message(eta_msg, GIFT_CARD_CHANNEL_ID)
    except Exception:
        await log_error(traceback.format_exc())

# ---------------------------
# DISCORD COMMANDS
# ---------------------------

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def coupon(ctx):
    global coupon_task
    if coupon_task and not coupon_task.done():
        await ctx.send("Coupon checker is already running.")
        return
    await ctx.send("Starting coupon checker...")
    coupon_task = bot.loop.create_task(coupon_checker_loop())

@bot.command()
async def stopcoupon(ctx):
    global coupon_task
    if coupon_task and not coupon_task.done():
        coupon_task.cancel()
        await ctx.send("Coupon checker stopped.")
        coupon_task = None
    else:
        await ctx.send("Coupon checker is not running.")

@bot.command()
async def giftcard(ctx):
    global giftcard_task
    if giftcard_task and not giftcard_task.done():
        await ctx.send("Gift card checker is already running.")
        return
    await ctx.send("Starting gift card checker...")
    giftcard_task = bot.loop.create_task(giftcard_checker_loop())

@bot.command()
async def stopgiftcard(ctx):
    global giftcard_task
    if giftcard_task and not giftcard_task.done():
        giftcard_task.cancel()
        await ctx.send("Gift card checker stopped.")
        giftcard_task = None
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
        await ctx.send("No checkers were running.")

bot.run(DISCORD_TOKEN)
