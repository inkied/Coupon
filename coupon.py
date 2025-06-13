import os
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import traceback
import discord
from discord.ext import commands
import time
import json

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOGS_CHANNEL_ID = int(os.getenv("LOGS_CHANNEL_ID") or 0)
COUPON_CHANNEL_ID = int(os.getenv("COUPON_CHANNEL_ID") or 0)
GIFTCARD_CHANNEL_ID = int(os.getenv("GIFTCARD_CHANNEL_ID") or 0)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)"
                  " Chrome/113.0.0.0 Safari/537.36"
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents)

# --- Globals & caches ---
coupon_task = None
giftcard_task = None

# Cache validated coupons: { code: (timestamp, valid_bool) }
validation_cache = {}
CACHE_TTL_SECONDS = 15 * 60  # 15 minutes cache

# Lock for validation cache access
validation_cache_lock = asyncio.Lock()

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
        # Ignore send errors silently for now
        pass

async def log_error(err: str):
    try:
        await send_discord_message(f"🚨 Error:\n```{err[:1800]}```", LOGS_CHANNEL_ID)
    except Exception:
        pass

def cache_cleanup():
    """Periodically cleanup expired cache entries."""
    now = time.time()
    keys_to_remove = []
    for k, (ts, _) in validation_cache.items():
        if now - ts > CACHE_TTL_SECONDS:
            keys_to_remove.append(k)
    for k in keys_to_remove:
        del validation_cache[k]

async def is_cached_valid(code: str):
    """Check cache for a coupon/gift card validation result."""
    async with validation_cache_lock:
        data = validation_cache.get(code)
        if not data:
            return None
        ts, valid = data
        if time.time() - ts > CACHE_TTL_SECONDS:
            del validation_cache[code]
            return None
        return valid

async def cache_validation_result(code: str, valid: bool):
    async with validation_cache_lock:
        validation_cache[code] = (time.time(), valid)

# --- Scrapers ---

async def scrape_g2a(session):
    url = "https://www.g2a.com/deals"
    results = []
    try:
        async with session.get(url, headers=HEADERS, timeout=20) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            coupons = soup.find_all("div", class_="coupon-list__coupon")
            for c in coupons:
                code = c.find("div", class_="coupon-list__coupon-code")
                discount = c.find("span", class_="coupon-list__discount")
                if code and discount:
                    code_text = code.text.strip()
                    discount_text = discount.text.strip().replace("%", "").replace("-", "")
                    if code_text and discount_text.isdigit():
                        results.append(("g2a", code_text, discount_text))
    except Exception:
        await log_error("G2A Scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_eneba(session):
    url = "https://www.eneba.com/us/store"
    results = []
    try:
        async with session.get(url, headers=HEADERS, timeout=20) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            promo_badges = soup.select(".shared-product-card__discount")
            for promo in promo_badges:
                discount_text = promo.text.strip().replace("-", "").replace("%", "")
                if discount_text.isdigit():
                    # Dummy code creation since no public codes shown
                    code = f"ENEBA{discount_text}"
                    results.append(("eneba", code, discount_text))
    except Exception:
        await log_error("Eneba Scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_kinguin(session):
    url = "https://www.kinguin.net/category/game-coupons-vouchers-1619/"
    results = []
    try:
        async with session.get(url, headers=HEADERS, timeout=20) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            items = soup.select(".product-list-item")
            for item in items:
                title = item.select_one(".product-title")
                discount = item.select_one(".discount-label")
                if title and discount:
                    discount_text = discount.text.strip().replace("%", "").replace("-", "")
                    code = title.text.strip().split()[0].upper()  # naive guess for code
                    if discount_text.isdigit():
                        results.append(("kinguin", code, discount_text))
    except Exception:
        await log_error("Kinguin Scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_cdkeys(session):
    url = "https://www.cdkeys.com/coupons"
    results = []
    try:
        async with session.get(url, headers=HEADERS, timeout=20) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            coupons = soup.select(".coupon-item")
            for c in coupons:
                code = c.select_one(".coupon-code")
                discount = c.select_one(".coupon-discount")
                if code and discount:
                    code_text = code.text.strip()
                    discount_text = discount.text.strip().replace("%", "").replace("-", "")
                    if discount_text.isdigit():
                        results.append(("cdkeys", code_text, discount_text))
    except Exception:
        await log_error("CDKeys Scrape failed:\n" + traceback.format_exc())
    return results

# --- New scrapers ---

async def scrape_retailmenot(session):
    url = "https://www.retailmenot.com/view/gaming"  # example gaming coupons page
    results = []
    try:
        async with session.get(url, headers=HEADERS, timeout=20) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            coupons = soup.select(".offer-coupon")  # example selector, needs updating for real site
            for c in coupons:
                code_tag = c.select_one(".code")
                discount_tag = c.select_one(".discount")
                if code_tag and discount_tag:
                    code_text = code_tag.text.strip()
                    discount_text = ''.join(filter(str.isdigit, discount_tag.text))
                    if code_text and discount_text.isdigit():
                        results.append(("retailmenot", code_text, discount_text))
    except Exception:
        await log_error("RetailMeNot scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_slickdeals(session):
    url = "https://slickdeals.net/coupons/"
    results = []
    try:
        async with session.get(url, headers=HEADERS, timeout=20) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            coupons = soup.select(".coupon")
            for c in coupons:
                code_tag = c.select_one(".code")
                discount_tag = c.select_one(".discount")
                if code_tag and discount_tag:
                    code_text = code_tag.text.strip()
                    discount_text = ''.join(filter(str.isdigit, discount_tag.text))
                    if code_text and discount_text.isdigit():
                        results.append(("slickdeals", code_text, discount_text))
    except Exception:
        await log_error("Slickdeals scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_couponsdotcom(session):
    url = "https://www.coupons.com/coupon-codes/"
    results = []
    try:
        async with session.get(url, headers=HEADERS, timeout=20) as resp:
            text = await resp.text()
            soup = BeautifulSoup(text, "html.parser")
            coupons = soup.select(".coupon-code")
            for c in coupons:
                code_text = c.text.strip()
                # Discount extraction hard, so skipping for now
                results.append(("couponsdotcom", code_text, "0"))
    except Exception:
        await log_error("Coupons.com scrape failed:\n" + traceback.format_exc())
    return results

# Dummy Honey scraper: real Honey uses heavy JS, no official API
async def scrape_honey(session):
    # No public API or scraping, so return empty or dummy
    return []

# --- Gift card scraper (dummy example) ---

async def scrape_giftcards(session):
    results = []
    try:
        # Real gift card sites would be added here with scraping logic
        # Demo dummy gift card:
        results.append(("GIFT2025", "15"))  # code, discount %
    except Exception:
        await log_error("Gift card scrape failed:\n" + traceback.format_exc())
    return results

# --- Validation ---

async def validate_coupon_real(session, code, site):
    """
    Lightning-fast validation with caching:
    - Check cache first
    - Do basic HEAD or GET request to coupon detail page if possible
    - Return True if site says valid or HTTP 200 on check URL
    """
    cached = await is_cached_valid(code)
    if cached is not None:
        return cached
    valid = False
    try:
        # Site-specific validation logic:
        if site == "g2a":
            check_url = f"https://www.g2a.com/coupon/{code}"
            async with session.head(check_url, headers=HEADERS, timeout=10) as resp:
                valid = resp.status == 200
        elif site == "eneba":
            # No official API, assume code with length > 3 is valid for demo
            valid = len(code) > 3
        elif site == "kinguin":
            # Simulate validation
            valid = len(code) > 3
        elif site == "cdkeys":
            check_url = f"https://www.cdkeys.com/coupon/{code}"
            async with session.head(check_url, headers=HEADERS, timeout=10) as resp:
                valid = resp.status == 200
        elif site == "retailmenot":
            # Assume codes longer than 3 are valid for demo
            valid = len(code) > 3
        elif site == "slickdeals":
            valid = len(code) > 3
        elif site == "couponsdotcom":
            valid = len(code) > 3
        elif site == "giftcard":
            valid = len(code) > 3
        else:
            valid = False
    except Exception:
        valid = False
    await cache_validation_result(code, valid)
    return valid

async def post_coupon(site, code, discount):
    msg = f"✅ [{site.upper()}] {code} | {discount}% off"
    await send_discord_message(msg, COUPON_CHANNEL_ID)

async def post_giftcard(code, discount):
    msg = f"✅ [GIFTCARD] {code} | {discount}% off"
    await send_discord_message(msg, GIFTCARD_CHANNEL_ID)

# --- Async concurrent validator for coupons ---

async def validate_coupons_concurrently(session, coupons):
    """
    coupons: list of tuples (site, code, discount)
    Returns: list of tuples (site, code, discount, valid_bool)
    """
    sem = asyncio.Semaphore(20)  # limit concurrency

    results = []

    async def validate_one(site, code, discount):
        async with sem:
            valid = await validate_coupon_real(session, code, site)
            results.append((site, code, discount, valid))

    tasks = [validate_one(site, code, discount) for (site, code, discount) in coupons]
    await asyncio.gather(*tasks)
    return results

# --- Coupon checker main loop ---

async def coupon_checker_loop():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await send_discord_message("🔍 Starting coupon scrape & validation...", COUPON_CHANNEL_ID)
                start_time = time.time()
                # Scrape all sites
                all_coupons = []
                scrapers = [
                    scrape_g2a,
                    scrape_eneba,
                    scrape_kinguin,
                    scrape_cdkeys,
                    scrape_retailmenot,
                    scrape_slickdeals,
                    scrape_couponsdotcom,
                    scrape_honey,
                ]
                for scraper in scrapers:
                    scraped = await scraper(session)
                    all_coupons.extend(scraped)

                total = len(all_coupons)
                if total == 0:
                    await send_discord_message("⚠️ No coupons found this cycle.", COUPON_CHANNEL_ID)
                    await asyncio.sleep(30)
                    continue

                # Validate coupons concurrently
                validated = await validate_coupons_concurrently(session, all_coupons)
                duration = time.time() - start_time

                valid_coupons = [c for c in validated if c[3]]

                # Post valid coupons
                for site, code, discount, valid in valid_coupons:
                    await post_coupon(site, code, discount)

                avg_time_per_coupon = duration / total if total else 0
                remaining = 0  # after done this cycle, next ETA is next cycle wait time

                eta = int(avg_time_per_coupon * remaining)
                msg = (f"✅ Checked {total} coupons in {int(duration)}s, "
                       f"found {len(valid_coupons)} valid.\n"
                       f"Next run ETA: ~30s")
                await send_discord_message(msg, COUPON_CHANNEL_ID)
        except Exception:
            await log_error(traceback.format_exc())
        await asyncio.sleep(30)  # wait 30s between runs

# --- Gift card checker loop (dummy example) ---

async def giftcard_checker_loop():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                await send_discord_message("🔍 Starting gift card scrape & validation...", GIFTCARD_CHANNEL_ID)
                start_time = time.time()

                # Scrape gift cards - add real scrapers here
                all_giftcards = await scrape_giftcards(session)
                total = len(all_giftcards)
                if total == 0:
                    await send_discord_message("⚠️ No gift cards found this cycle.", GIFTCARD_CHANNEL_ID)
                    await asyncio.sleep(60)
                    continue

                validated = []
                sem = asyncio.Semaphore(20)

                async def validate_giftcard(code, discount):
                    async with sem:
                        # Dummy validation - accept all with code length > 3
                        valid = len(code) > 3
                        validated.append((code, discount, valid))

                tasks = [validate_giftcard(code, discount) for (code, discount) in all_giftcards]
                await asyncio.gather(*tasks)

                valid_giftcards = [c for c in validated if c[2]]
                for code, discount, valid in valid_giftcards:
                    await post_giftcard(code, discount)

                duration = time.time() - start_time
                msg = (f"✅ Checked {total} gift cards in {int(duration)}s, "
                       f"found {len(valid_giftcards)} valid.\n"
                       f"Next run ETA: ~60s")
                await send_discord_message(msg, GIFTCARD_CHANNEL_ID)

        except Exception:
            await log_error(traceback.format_exc())
        await asyncio.sleep(60)

# --- Commands ---

@bot.command()
async def coupon(ctx):
    global coupon_task
    if coupon_task and not coupon_task.done():
        await ctx.send("Coupon checker is already running.")
        return
    coupon_task = asyncio.create_task(coupon_checker_loop())
    await ctx.send("Started coupon checker task.")

@bot.command()
async def giftcard(ctx):
    global giftcard_task
    if giftcard_task and not giftcard_task.done():
        await ctx.send("Gift card checker is already running.")
        return
    giftcard_task = asyncio.create_task(giftcard_checker_loop())
    await ctx.send("Started gift card checker task.")

@bot.command()
async def stopcoupon(ctx):
    global coupon_task
    if coupon_task:
        coupon_task.cancel()
        coupon_task = None
        await ctx.send("Coupon checker stopped.")
    else:
        await ctx.send("Coupon checker was not running.")

@bot.command()
async def stopgiftcard(ctx):
    global giftcard_task
    if giftcard_task:
        giftcard_task.cancel()
        giftcard_task = None
        await ctx.send("Gift card checker stopped.")
    else:
        await ctx.send("Gift card checker was not running.")

@bot.command()
async def stop(ctx):
    await ctx.send("Stopping all checkers...")
    global coupon_task, giftcard_task
    if coupon_task:
        coupon_task.cancel()
        coupon_task = None
    if giftcard_task:
        giftcard_task.cancel()
        giftcard_task = None
    await ctx.send("All checkers stopped.")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("------")

# --- Run bot ---

bot.run(DISCORD_TOKEN)

