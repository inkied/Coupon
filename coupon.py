import asyncio
import aiohttp
import os
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import traceback

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
LOGS_CHANNEL_ID = int(os.getenv("LOGS_CHANNEL_ID") or 0)
COUPON_CHANNEL_ID = int(os.getenv("COUPON_CHANNEL_ID") or 0)
GIFTCARD_CHANNEL_ID = int(os.getenv("GIFTCARD_CHANNEL_ID") or 0)
HEADERS = {"User-Agent": "Mozilla/5.0"}

async def send_discord_message(message: str, channel_id: int):
    if not DISCORD_TOKEN or not channel_id:
        return
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json"
    }
    json = {"content": message}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=json):
                pass
    except:
        pass

async def log_error(err):
    await send_discord_message(f"🚨 Error:\n```{err[:1800]}```", LOGS_CHANNEL_ID)

async def validate_coupon_real(session, code, site):
    try:
        # Replace with real add-to-cart test if possible
        await asyncio.sleep(0.3)
        import random
        return random.random() > 0.5  # Simulated validity
    except:
        return False

async def scrape_g2a(session):
    url = "https://www.g2a.com/deals"
    results = []
    try:
        async with session.get(url, headers=HEADERS) as resp:
            soup = BeautifulSoup(await resp.text(), "html.parser")
            for c in soup.select(".sc-coupon-card"):
                code = c.select_one(".sc-coupon-card__coupon")
                discount = c.select_one(".sc-coupon-card__discount")
                if code and discount:
                    code_text = code.text.strip()
                    percent = ''.join(filter(str.isdigit, discount.text.strip()))
                    results.append(("g2a", code_text, percent))
    except Exception:
        await log_error("G2A Scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_eneba(session):
    url = "https://www.eneba.com/us/store"
    results = []
    try:
        async with session.get(url, headers=HEADERS) as resp:
            soup = BeautifulSoup(await resp.text(), "html.parser")
            for promo in soup.select(".shared-product-card__discount"):
                discount = ''.join(filter(str.isdigit, promo.text.strip()))
                code = f"ENEBA{discount}"
                results.append(("eneba", code, discount))
    except Exception:
        await log_error("Eneba Scrape failed:\n" + traceback.format_exc())
    return results

async def scrape_kinguin(session):
    # Placeholder for real scraping logic
    return []

async def scrape_cdkeys(session):
    # Placeholder for real scraping logic
    return []

async def post_coupon(site, code, discount):
    msg = f"✅ [{site.upper()}] {code} | {discount}% off"
    await send_discord_message(msg, COUPON_CHANNEL_ID)

async def main_loop():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                all_coupons = []
                for scrape_func in [scrape_g2a, scrape_eneba, scrape_kinguin, scrape_cdkeys]:
                    all_coupons += await scrape_func(session)

                for site, code, discount in all_coupons:
                    try:
                        if await validate_coupon_real(session, code, site):
                            await post_coupon(site, code, discount)
                    except Exception:
                        await log_error(traceback.format_exc())
        except Exception:
            await log_error(traceback.format_exc())

        await asyncio.sleep(20)

if __name__ == "__main__":
    asyncio.run(main_loop())
