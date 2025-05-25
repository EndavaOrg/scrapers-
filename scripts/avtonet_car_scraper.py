import asyncio
import random
import warnings
import os
import csv
import aiofiles

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from motor.motor_asyncio import AsyncIOMotorClient
from cryptography.utils import CryptographyDeprecationWarning
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
COLLECTION_NAME = os.getenv("COLLECTION_NAME")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
cars_collection = db[COLLECTION_NAME]


async def scrape_page(page):
    # Wait for results to appear
    try:
        await page.wait_for_selector("div.row.bg-white", timeout=60000)
    except Exception as e:
        print(f"Error waiting for car results: {e}")
        return

    cars = await page.query_selector_all("div.row.bg-white")

    for car in cars:
        # Declare variables for elements
        full_name_element = await car.query_selector("div.GO-Results-Naziv span")  # Car make element
        # reg_price_element = await car.query_selector("div.GO-Results-Top-Price-TXT-Regular")  # Car regular price element
        reg_price_element = await query_fallback(car, ["div.GO-Results-Top-Price-TXT-Regular", "div.GO-Results-Price-TXT-Regular"])
        # special_price_element = await car.query_selector("div.GO-Results-Top-Price-TXT-AkcijaCena")  # Car special price element
        special_price_element = await query_fallback(car, ["div.GO-Results-Top-Price-TXT-Regular", "div.GO-Results-Price-TXT-AkcijaCena"])
        table_element = await car.query_selector("table.table.table-striped.table-sm.table-borderless.font-weight-normal") # Car table element
        # img_element = await car.query_selector("div.GO-Results-Top-PhotoTop a img")  # Car image element
        img_element = await query_fallback(car, ["div.GO-Results-Top-PhotoTop a img", "div.col-auto.p-3.GO-Results-Photo div a img"])
        link_element = await car.query_selector("a.stretched-link")

        full_name = await full_name_element.inner_text() if full_name_element else ""  # Car full name
        name_parts = full_name.strip().split()

        # Extract make and model parts
        make_value = check_special_make(name_parts)
        model_value = check_special_model(make_value, name_parts)

        # Extract price
        price_value = await extract_price(reg_price_element, special_price_element)

        # Extract specs from table
        specs = await extract_specs_from_table(car, table_element)

        # Extract engine information
        engine_ccm_value, engine_kw_value, engine_hp_value = extract_engine_info(specs.get("Motor"))

        # Extract first reg, mileage, battery
        first_reg_value = int(specs.get("1.registracija").strip()) if specs.get("1.registracija") else None
        mileage_value = int(specs.get("Prevoženih").replace(" km", "").strip()) if specs.get("Prevoženih") else None
        battery_value = float(specs.get("Baterija").replace(" kWh", "").replace(",", ".").strip()) if specs.get("Baterija") else None

        # Extract image URL
        if img_element is not None and link_element is not None:
            img_url = await img_element.get_attribute('src')
            href_attribute = await link_element.get_attribute('href')
            link = href_attribute.replace("..", "https://www.avto.net")
        else:
            img_url, link = None, None

        # Car Data
        car_data = {
            "make": make_value,
            "model": model_value,
            "price_eur": price_value,
            "first_registration": first_reg_value,
            "mileage_km": mileage_value,
            "fuel_type": specs.get("Gorivo"),
            "gearbox": specs.get("Menjalnik"),
            "engine_ccm": engine_ccm_value,
            "engine_kw": engine_kw_value,
            "engine_hp": engine_hp_value,
            "battery_kwh": battery_value,
            "state": specs.get("Starost"),
            "image_url": img_url,
            "link": link
        }

        print(car_data)
        # await cars_collection.insert_one(car_data)

async def scrape():
    await cars_collection.delete_many({})

    start_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=0&ccmMin=0&ccmMax=99999&mocMin=0&mocMax=999999&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=0&dolzina=&dolzinaMIN=0&dolzinaMAX=100&nosilnostMIN=0&nosilnostMAX=999999&sedezevMIN=0&sedezevMAX=9&lezisc=&presek=0&premer=0&col=0&vijakov=0&EToznaka=0&vozilo=&airbag=&barva=&barvaint=&doseg=0&BkType=0&BkOkvir=0&BkOkvirType=0&Bk4=0&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=1000000020&EQ10=1000000000&KAT=1010000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=0&paketgarancije=&broker=0&prikazkategorije=0&kategorija=0&ONLvid=0&ONLnak=0&zaloga=10&arhiv=0&presort=3&tipsort=DESC&stran=1"

    n_pages = 25  # Number of pages to scrape

    for i in range(1, n_pages + 1):
        print(f"\nScraping page {i}...")
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="en-US"
            )

            page = await context.new_page()
            await stealth_async(page)

            # Construct URL for the current page
            page_url = start_url.replace("stran=1", f"stran={i}")
            try:
                await page.goto(page_url, timeout=60000)
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(random.uniform(3, 6))  # Random delay to mimic human behavior

                # Scrape the page
                await scrape_page(page)

            except Exception as e:
                print(f"Error on page {i}: {e}")
                await page.screenshot(path=f"screenshot_error_page_{i}.png")
                await browser.close()
                break

            await browser.close()
    
    print(f"\nScraping completed.")


# ---------- Helper functions ----------
async def query_fallback(page, selectors: list[str]):
    for s in selectors:
        element = await page.query_selector(s)
        if element:
            return element
    return None

def check_special_make(name_parts: list[str]) -> str | None:
    if not name_parts:
        return None

    multi_word_makes = {
        ("Land", "Rover"): "Land Rover",
        ("Alfa", "Romeo"): "Alfa Romeo",
        ("Aston", "Martin"): "Aston Martin",
        ("Rolls", "Royce"): "Rolls Royce",
        ("DS", "Automobiles"): "DS Automobiles"
    }

    for key_tuple, full_make in multi_word_makes.items():
        if name_parts[:len(key_tuple)] == list(key_tuple):
            return full_make

    return name_parts[0]

def check_special_model(make: str, name_parts: list[str]) -> str | None:
    if not name_parts or len(name_parts) < 2:
        return None

    offset = len(make.split())
    try:
        match make:
            case "BMW":
                if name_parts[offset].lower() == "serija":
                    return f"{name_parts[offset]} {name_parts[offset+1]}".replace(":", "")
                return name_parts[offset]
            case "Land Rover":
                if name_parts[offset].lower() == "range":
                    return f"{name_parts[offset]} {name_parts[offset+1]}"
                return name_parts[offset]
            case _:
                return name_parts[offset]
    except IndexError:
        return None

async def extract_specs_from_table(car, table_element):
    specs = {}
    table = table_element
    if table:
        rows = await table.query_selector_all("tr")
        for row in rows:
            cells = await row.query_selector_all("td")
            if len(cells) == 2:
                key = (await cells[0].inner_text()).strip()
                value = (await cells[1].inner_text()).strip()
                specs[key] = value
    return specs

async def extract_price(reg_price_element, special_price_element):
    for price_element in [reg_price_element, special_price_element]:
        if price_element:
            try:
                price_text = (await price_element.inner_text()).replace(" €", "").replace(".", "").strip()
                return int(price_text)
            except:
                continue
    return None

def extract_engine_info(engine_info):
    engine_ccm = None
    engine_kw = None
    engine_hp = None

    if engine_info:
        parts = engine_info.strip().split()
        try:
            engine_ccm = int(parts[0])
            engine_kw = int(parts[2])
            engine_hp = int(parts[-2])
        except (IndexError, ValueError):
            pass

    return engine_ccm, engine_kw, engine_hp


# Run the scraper
asyncio.run(scrape())