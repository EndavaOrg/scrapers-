import asyncio
import os
import sys
import logging
import warnings

from motor.motor_asyncio import AsyncIOMotorClient
from cryptography.utils import CryptographyDeprecationWarning
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from tenacity import retry, stop_after_attempt, wait_exponential

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

# Configure logging for GitHub Actions
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

mongo_uri = os.environ.get("MONGO_URI")
if not mongo_uri:
    raise RuntimeError("MONGO_URI not set in environment variables.")

client = AsyncIOMotorClient(mongo_uri)
db = client["primerjalnik_cen_db"]
car_collection = db["cars"]
moto_collection = db["motorcycles"]
truck_collection = db["trucks"]

async def cleanup_outdated_vehicles(collection, site_name: str, semaphore: asyncio.Semaphore):
    async with async_playwright() as p:
        try:
            cursor = collection.find({}, {"link": 1})
            links = [doc["link"] async for doc in cursor]
            filtered_links = [link for link in links if site_name in link]
            logger.info(f"Checking {len(filtered_links)} vehicle links for validity from site: {site_name}, collection: {collection.name}")

            batch_size = 30
            for i in range(0, len(filtered_links), batch_size):
                batch_links = filtered_links[i:i + batch_size]
                logger.info(f"Processing batch of {len(batch_links)} links (links {i+1} to {i+len(batch_links)}) for collection: {collection.name}")
                
                invalid_links = []
                async with semaphore:  # Limit concurrent browser instances
                    browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
                    context = await browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                        viewport={"width": 1280, "height": 720},
                        locale="en-US"
                    )

                    tasks = [check_vehicle_page_validity(context, link, site_name) for link in batch_links]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for link, is_valid in zip(batch_links, results):
                        logger.info(f"Checked link: {link}, Valid: {is_valid}, collection: {collection.name}")
                        if not is_valid:
                            invalid_links.append(link)

                    await context.close()
                    await browser.close()
                    logger.info(f"Closed browser for batch {i//batch_size + 1}, collection: {collection.name}")
                
                # Delete invalid links for this batch in real time
                if invalid_links:
                    result = await collection.delete_many({"link": {"$in": invalid_links}})
                    logger.info(f"Removed {result.deleted_count} outdated vehicles with invalid links from batch {i//batch_size + 1}, collection: {collection.name}")
                
                await asyncio.sleep(0.5)

            logger.info(f"Completed cleanup for collection: {collection.name}, site: {site_name}")
        except Exception as e:
            logger.error(f"Error during cleanup of outdated vehicles for {site_name}, collection: {collection.name}: {e}")

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
async def check_vehicle_page_validity(context, link: str, site_name: str) -> bool:
    if site_name not in ["avto.net", "autobid.de"]:
        logger.info(f"Skipping validation for {link} (site {site_name} not in allowed list [avto.net, autobid.de])")
        return True
    page = await context.new_page()
    await stealth_async(page)
    try:
        response = await page.goto(link, timeout=15000)
        if site_name == "avto.net":
            current_url = page.url
            if current_url == "https://www.avto.net/unvalid.asp":
                logger.info(f"Redirected to unvalid.asp for link: {link}")
                return False
            return True
        elif site_name == "autobid.de":
            error_element = await page.query_selector('div.container.mx-auto.h-full span[style*="font-size:35px;"]:contains("Stran ni bila najdena")')
            if error_element:
                logger.info(f"Error page detected for link: {link} (Stran ni bila najdena)")
                return False
            return True
    except Exception as e:
        logger.error(f"Error checking link {link} for {site_name}: {e}")
        return False
    finally:
        await page.close()

async def cleanup_all_collections(site_name: str):
    semaphore = asyncio.Semaphore(3)  # Limit to 3 concurrent browsers
    collections = [car_collection, moto_collection, truck_collection]
    logger.info(f"Starting concurrent cleanup for all collections with site: {site_name}")
    tasks = [cleanup_outdated_vehicles(collection, site_name, semaphore) for collection in collections]
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(f"Completed cleanup for all collections with site: {site_name}")

async def cleanup_all_sites():
    await cleanup_all_collections("avto.net")
    await cleanup_all_collections("autobid.de")

if __name__ == "__main__":
    asyncio.run(cleanup_all_sites())