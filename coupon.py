import os
import asyncio
import aiohttp
from aiohttp import ClientTimeout
import discord
from discord.ext import commands, tasks
from datetime import datetime
import traceback
import json
import re

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOGS_CHANNEL_ID = int(os.getenv("LOGS_CHANNEL_ID", 0))
COUPON_CHANNEL_ID = int(os.getenv("COUPON_CHANNEL_ID", 0))
GIFTCARD_CHANNEL_ID = int(os.getenv("GIFTCARD_CHANNEL_ID", 0))

BASE_CONCURRENCY = 20
MAX_CONCURRENCY = 50
MIN_CONCURRENCY = 5

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5

concurrency = BASE_CONCURRENCY
sem = asyncio.Semaphore(concurrency)

intents = discord.Intents.default()
bot = commands.Bot(command_prefix=".", intents=intents)

posted_coupons = set()
posted_giftcards = set()

stats = {
    "coupons_checked": 0,
    "coupons_posted": 0,
    "coupons_failed": 0,
    "giftcards_checked": 0,
    "giftcards_posted": 0,
    "giftcards_failed": 0,
    "retries": 0,
    "rate_limited": 0,
    "start_time": datetime.utcnow()
}

error_window = []
RATE_LIMIT_THRESHOLD = 5
ERROR_WINDOW_SIZE = 20

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01"
}

async def safe_fetch(session, url, headers=None, timeout=15):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with sem, session.get(url, headers=headers or HEADERS, timeout=ClientTimeout(total=timeout)) as resp:
                if resp.status == 429:
                    stats["rate_limited"] += 1
                    await asyncio.sleep(5 * attempt)
                    continue
                if resp.status >= 400:
                    return None, f"HTTP {resp.status}"
                data = await resp.text()
                return data, None
        except asyncio.TimeoutError:
            if attempt == MAX_RETRIES:
                return None, "TimeoutError"
        except aiohttp.ClientError as e:
            if attempt == MAX_RETRIES:
                return None, f"ClientError: {str(e)}"
        await asyncio.sleep(RETRY_BACKOFF_BASE ** attempt)
        stats["retries"] += 1
    return None, "Max retries exceeded"

def adjust_concurrency():
    global concurrency, sem
    if len(error_window) < ERROR_WINDOW_SIZE:
        return
    rate_limits = sum(error_window)
    if rate_limits >= RATE_LIMIT_THRESHOLD and concurrency > MIN_CONCURRENCY:
        concurrency = max(MIN_CONCURRENCY, concurrency // 2)
        sem = asyncio.Semaphore(concurrency)
    elif rate_limits < RATE_LIMIT_THRESHOLD // 2 and concurrency < MAX_CONCURRENCY:
        concurrency = min(MAX_CONCURRENCY, concurrency + 5)
        sem = asyncio.Semaphore(concurrency)

async def log_error(site, err):
    logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
    if logs_channel:
        clean_msg = str(err).strip().replace("```", "")
        embed = discord.Embed(
            title=f"🚨 Error in {site} scraper",
            description=f"```{clean_msg}```",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        await logs_channel.send(embed=embed)
    else:
        print(f"Logs channel missing. Error from {site}: {err}")

async def post_coupon(site_name, code, discount_percent, discount_amount_str, expiration):
    channel = bot.get_channel(COUPON_CHANNEL_ID)
    if not channel:
        print("Coupon channel not found.")
        return
    if code in posted_coupons:
        return
    posted_coupons.add(code)
    stats["coupons_posted"] += 1
    embed = discord.Embed(
        title=f"Coupon from {site_name}",
        description=f"**Code:** `{code}`\n**Discount:** {discount_percent}% ({discount_amount_str})\n**Expires:** {expiration}",
        color=discord.Color.green(),
        timestamp=datetime.utcnow()
    )
    await channel.send(embed=embed)

# ------------------ SCRAPERS ------------------

async def scrape_g2a(session):
    url = "https://www.g2a.com/api/v1/coupons"
    data, err = await safe_fetch(session, url)
    if err:
        await log_error("G2A", err)
        error_window.append(1)
        adjust_concurrency()
        stats["coupons_failed"] += 1
        return
    error_window.append(0)
    adjust_concurrency()

    try:
        j = json.loads(data)
        coupons = j.get("coupons", [])
        for c in coupons:
            code = c.get("code", "").strip()
            discount_percent = int(c.get("discountPercent", 0))
            discount_amount_str = f"${c.get('discountAmount', '0')}"
            expiration = c.get("expirationDate", "N/A")
            stats["coupons_checked"] += 1
            yield (code, discount_percent, discount_amount_str, expiration)
    except Exception as e:
        await log_error("G2A", f"Parsing error: {e}")

async def scrape_eneba(session):
    url = "https://api.eneba.com/v1/coupons"
    data, err = await safe_fetch(session, url)
    if err:
        await log_error("Eneba", err)
        error_window.append(1)
        adjust_concurrency()
        stats["coupons_failed"] += 1
        return
    error_window.append(0)
    adjust_concurrency()

    try:
        j = json.loads(data)
        coupons = j.get("data", [])
        for c in coupons:
            code = c.get("code", "").strip()
            discount_percent = int(c.get("discount", 0))
            discount_amount_str = f"${c.get('discountAmount', '0')}"
            expiration = c.get("expiryDate", "N/A")
            stats["coupons_checked"] += 1
            yield (code, discount_percent, discount_amount_str, expiration)
    except Exception as e:
        await log_error("Eneba", f"Parsing error: {e}")

async def scrape_kinguin(session):
    url = "https://www.kinguin.net/api/v1/promotions/coupons"
    data, err = await safe_fetch(session, url)
    if err:
        await log_error("Kinguin", err)
        error_window.append(1)
        adjust_concurrency()
        stats["coupons_failed"] += 1
        return
    error_window.append(0)
    adjust_concurrency()

    try:
        j = json.loads(data)
        coupons = j.get("data", [])
        for c in coupons:
            code = c.get("code", "").strip()
            discount_percent = int(c.get("discountPercent", 0))
            discount_amount_str = f"${c.get('discountAmount', '0')}"
            expiration = c.get("expiresAt", "N/A")
            stats["coupons_checked"] += 1
            yield (code, discount_percent, discount_amount_str, expiration)
    except Exception as e:
        await log_error("Kinguin", f"Parsing error: {e}")

async def scrape_cdkeys(session):
    url = "https://api.cdkeys.com/v1/coupons"
    data, err = await safe_fetch(session, url)
    if err:
        await log_error("CDKeys", err)
        error_window.append(1)
        adjust_concurrency()
        stats["coupons_failed"] += 1
        return
    error_window.append(0)
    adjust_concurrency()

    try:
        j = json.loads(data)
        coupons = j.get("coupons", [])
        for c in coupons:
            code = c.get("code", "").strip()
            discount_percent = int(c.get("discountPercent", 0))
            discount_amount_str = f"${c.get('discountAmount', '0')}"
            expiration = c.get("validUntil", "N/A")
            stats["coupons_checked"] += 1
            yield (code, discount_percent, discount_amount_str, expiration)
    except Exception as e:
        await log_error("CDKeys", f"Parsing error: {e}")

async def scrape_coupert(session):
    url = "https://coupert.com/api/v1/coupons"
    data, err = await safe_fetch(session, url)
    if err:
        await log_error("Coupert", err)
        error_window.append(1)
        adjust_concurrency()
        stats["coupons_failed"] += 1
        return
    error_window.append(0)
    adjust_concurrency()

    try:
        j = json.loads(data)
        coupons = j.get("results", [])
        for c in coupons:
            code = c.get("code", "").strip()
            discount_percent = int(c.get("discountPercent", 0))
            discount_amount_str = f"${c.get('discountAmount', '0')}"
            expiration = c.get("expiryDate", "N/A")
            stats["coupons_checked"] += 1
            yield (code, discount_percent, discount_amount_str, expiration)
    except Exception as e:
        await log_error("Coupert", f"Parsing error: {e}")

async def scrape_honey(session):
    url = "https://api.joinhoney.com/api/v1/coupons"
    data, err = await safe_fetch(session, url)
    if err:
        await log_error("Honey", err)
        error_window.append(1)
        adjust_concurrency()
        stats["coupons_failed"] += 1
        return
    error_window.append(0)
    adjust_concurrency()

    try:
        j = json.loads(data)
        coupons = j.get("coupons", [])
        for c in coupons:
            code = c.get("code", "").strip()
            discount_percent = int(c.get("discountPercent", 0))
            discount_amount_str = f"${c.get('discountAmount', '0')}"
            expiration = c.get("expiresAt", "N/A")
            stats["coupons_checked"] += 1
            yield (code, discount_percent, discount_amount_str, expiration)
    except Exception as e:
        await log_error("Honey", f"Parsing error: {e}")

async def scrape_slickdeals(session):
    url = "https://slickdeals.net/api/v1/coupons"
    data, err = await safe_fetch(session, url)
    if err:
        await log_error("SlickDeals", err)
        error_window.append(1)
        adjust_concurrency()
        stats["coupons_failed"] += 1
        return
    error_window.append(0)
    adjust_concurrency()

    try:
        j = json.loads(data)
        coupons = j.get("coupons", [])
        for c in coupons:
            code = c.get("couponCode", "").strip()
            discount_percent = int(c.get("discountPercent", 0))
            discount_amount_str = f"${c.get('discountAmount', '0')}"
            expiration = c.get("expiryDate", "N/A")
            stats["coupons_checked"] += 1
            yield (code, discount_percent, discount_amount_str, expiration)
    except Exception as e:
        await log_error("SlickDeals", f"Parsing error: {e}")

# -------------- COMMANDS --------------

@bot.command()
async def coupon(ctx):
    await ctx.send("Starting coupon scrape & validation...")

    async with aiohttp.ClientSession() as session:
        scrapers = [
            scrape_g2a(session),
            scrape_eneba(session),
            scrape_kinguin(session),
            scrape_cdkeys(session),
            scrape_coupert(session),
            scrape_honey(session),
            scrape_slickdeals(session),
        ]
        for scraper in scrapers:
            async for coupon_data in scraper:
                code, discount_percent, discount_amount_str, expiration = coupon_data
                await post_coupon("CouponSite", code, discount_percent, discount_amount_str, expiration)
                await asyncio.sleep(1)  # post one by one

@bot.command()
async def purge_logs(ctx, amount: int = 50):
    logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
    if logs_channel:
        deleted = await logs_channel.purge(limit=amount)
        await ctx.send(f"Purged {len(deleted)} messages in logs.")
    else:
        await ctx.send("Logs channel not found.")

@tasks.loop(minutes=5)
async def stats_report():
    logs_channel = bot.get_channel(LOGS_CHANNEL_ID)
    if not logs_channel:
        return
    uptime = datetime.utcnow() - stats["start_time"]
    embed = discord.Embed(
        title="Coupon Checker Stats",
        color=discord.Color.gold(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Uptime", value=str(uptime).split('.')[0], inline=False)
    embed.add_field(name="Coupons Checked", value=str(stats["coupons_checked"]))
    embed.add_field(name="Coupons Posted", value=str(stats["coupons_posted"]))
    embed.add_field(name="Coupon Failures", value=str(stats["coupons_failed"]))
    embed.add_field(name="Retries", value=str(stats["retries"]))
    embed.add_field(name="Rate Limits", value=str(stats["rate_limited"]))
    embed.add_field(name="Current Concurrency", value=str(concurrency))
    await logs_channel.send(embed=embed)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    stats_report.start()

bot.run(DISCORD_TOKEN)
