import os
import discord
from discord.ext import commands
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime

# Environment variables expected:
# DISCORD_TOKEN - your Discord bot token
# COUPON_CHANNEL_ID - channel ID for .coupons command (int)
# GIFT_CHANNEL_ID - channel ID for .gift command (int)

COUPON_CHANNEL_ID = int(os.getenv("COUPON_CHANNEL_ID", "1383056551996293120"))
GIFT_CHANNEL_ID = int(os.getenv("GIFT_CHANNEL_ID", "1383056616668139582"))

intents = discord.Intents.default()
bot = commands.Bot(command_prefix='.', intents=intents)

# -------------------------
# Coupon sources & dummy coupons for demo.
# Replace these with real coupon fetch + validation logic.
GAME_COUPONS = [
    {"store":"G2A", "code":"SAVE20", "valid_until":"June 30, 2025", "last_worked":"June 13, 2025", "used_count":12, "original_price":50.0, "discounted_price":40.0},
    {"store":"Eneba", "code":"XMAS15", "valid_until":"July 5, 2025", "last_worked":"June 12, 2025", "used_count":5, "original_price":60.0, "discounted_price":51.0},
]

GIFT_COUPONS = [
    {"store":"Eneba", "code":"GIFT10", "valid_until":"Dec 31, 2025", "last_worked":"June 10, 2025", "used_count":3, "original_price":100.0, "discounted_price":90.0},
    {"store":"Kinguin", "code":"GIFT5OFF", "valid_until":"Aug 15, 2025", "last_worked":"June 1, 2025", "used_count":7, "original_price":50.0, "discounted_price":45.0},
]

# -------------------------
# Playwright coupon validator stub - simulate async validation
async def validate_coupon(playwright, coupon):
    # In real code, launch Chromium and simulate checkout to test coupon validity and get discount
    # Here we just "simulate" validation delay and accept all coupons for demo
    await asyncio.sleep(0.3)  # simulate network delay and validation
    # For demo: mark all coupons valid and working
    coupon["works"] = True
    return coupon

async def validate_coupons(coupons):
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        # Could optimize by reusing context for all coupons if you want
        tasks = []
        for coupon in coupons:
            tasks.append(validate_coupon(browser, coupon))
        results = await asyncio.gather(*tasks)
        await browser.close()
    return results

def format_coupon(coupon):
    discount_pct = int(100*(1 - coupon["discounted_price"]/coupon["original_price"]))
    return (f"[{coupon['store']}] `{coupon['code']}` ✅ | Valid Until {coupon['valid_until']} | "
            f"Last worked {coupon['last_worked']} | Used {coupon['used_count']} times\n"
            f"Original: ${coupon['original_price']:.2f} → After Coupon: ${coupon['discounted_price']:.2f} ({discount_pct}% OFF)")

def group_and_sort_coupons(coupons):
    # Filter only working coupons
    coupons = [c for c in coupons if c.get("works")]
    # Sort descending by discount %
    coupons.sort(key=lambda c: (1 - c["discounted_price"]/c["original_price"]), reverse=True)
    grouped = {}
    for c in coupons:
        grouped.setdefault(c["store"], []).append(c)
    return grouped

@bot.command()
async def coupons(ctx):
    if ctx.channel.id != COUPON_CHANNEL_ID:
        await ctx.reply(f"This command can only be used in the Coupon Checker channel.")
        return
    await ctx.send("Fetching and validating game coupons, please wait...")
    validated = await validate_coupons(GAME_COUPONS)
    grouped = group_and_sort_coupons(validated)
    if not grouped:
        await ctx.send("No valid coupons found right now.")
        return
    for store, coupons in grouped.items():
        msg = f"**[{store}]**\n" + "\n".join(format_coupon(c) for c in coupons)
        await ctx.send(msg)
        await asyncio.sleep(1)

@bot.command()
async def gift(ctx):
    if ctx.channel.id != GIFT_CHANNEL_ID:
        await ctx.reply(f"This command can only be used in the Gift Card Checker channel.")
        return
    await ctx.send("Fetching and validating gift card coupons, please wait...")
    validated = await validate_coupons(GIFT_COUPONS)
    grouped = group_and_sort_coupons(validated)
    if not grouped:
        await ctx.send("No valid gift card coupons found right now.")
        return
    for store, coupons in grouped.items():
        msg = f"**[{store}]**\n" + "\n".join(format_coupon(c) for c in coupons)
        await ctx.send(msg)
        await asyncio.sleep(1)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    print("Bot is ready.")

if __name__ == "__main__":
    TOKEN = os.getenv("DISCORD_TOKEN")
    if not TOKEN:
        print("Error: DISCORD_TOKEN environment variable not set!")
        exit(1)
    bot.run(TOKEN)
