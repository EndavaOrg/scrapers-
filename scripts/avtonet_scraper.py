import asyncio
import random
import warnings
import os
import re

from typing import Dict, Callable, Any, Optional
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from motor.motor_asyncio import AsyncIOMotorClient
from cryptography.utils import CryptographyDeprecationWarning
from dotenv import load_dotenv

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
COLLECTIONS = os.getenv("COLLECTIONS", "").split(",")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
car_collection = db[COLLECTIONS[0]]
moto_collection = db[COLLECTIONS[1]]

# ---------- Configuration for Cars and Motorcycles ----------
CAR_FIELDS = {
    "make": {"source": "name_parts", "processor": lambda np: check_special_make(np)},
    "model": {"source": "name_parts", "processor": lambda np, make: check_special_model(make, np)},
    "price_eur": {"source": "price", "processor": lambda price_tuple: price_tuple},
    "first_registration": {"source": "specs", "processor": lambda s: int(s.get("1.registracija").strip()) if s.get("1.registracija") else None},
    "mileage_km": {"source": "specs", "processor": lambda s: int(s.get("Prevoženih").replace(" km", "").strip()) if s.get("Prevoženih") else None},
    "fuel_type": {"source": "specs", "processor": lambda s: s.get("Gorivo")},
    "gearbox": {"source": "specs", "processor": lambda s: s.get("Menjalnik")},
    "engine_ccm": {"source": "engine", "processor": lambda e: extract_engine_info(e, is_motorcycle=False)[0]},
    "engine_kw": {"source": "engine", "processor": lambda e: extract_engine_info(e, is_motorcycle=False)[1]},
    "engine_hp": {"source": "engine", "processor": lambda e: extract_engine_info(e, is_motorcycle=False)[2]},
    "battery_kwh": {"source": "specs", "processor": lambda s: float(s.get("Baterija").replace(" kWh", "").replace(",", ".").strip()) if s.get("Baterija") else None},
    "state": {"source": "specs", "processor": lambda s: s.get("Starost") if s.get("Starost") else "RABLJENO"},
    "image_url": {"source": "img_element", "processor": lambda img, _: img},
    "link": {"source": "link_element", "processor": lambda _, link: link}
}

MOTORCYCLE_FIELDS = {
    "make": {"source": "name_parts", "processor": lambda np: check_special_make(np)},
    "model": {"source": "name_parts", "processor": lambda np, make: check_special_model(make, np)},
    "price_eur": {"source": "price", "processor": lambda price_tuple: price_tuple},
    "first_registration": {"source": "specs", "processor": lambda s: int(s.get("1.registracija").strip()) if s.get("1.registracija") else None},
    "mileage_km": {"source": "specs", "processor": lambda s: int(s.get("Prevoženih").replace(" km", "").strip()) if s.get("Prevoženih") else None},
    "engine_kw": {"source": "engine", "processor": lambda e: extract_engine_info(e, is_motorcycle=True)[1]},
    "engine_hp": {"source": "engine", "processor": lambda e: extract_engine_info(e, is_motorcycle=True)[2]},
    "state": {"source": "specs", "processor": lambda s: s.get("Starost") if s.get("Starost") else "RABLJENO"},
    "image_url": {"source": "img_element", "processor": lambda img, _: img},
    "link": {"source": "link_element", "processor": lambda _, link: link}
}

async def scrape_page(page, fields: Dict[str, Dict[str, Any]], collection):
    try:
        await page.wait_for_selector("div.row.bg-white", timeout=60000)
    except Exception as e:
        print(f"Error waiting for results: {e}")
        return

    vehicles = await page.query_selector_all("div.row.bg-white.position-relative.GO-Results-Row.GO-Shadow-B, div.row.bg-white.mb-3.pb-3.pb-sm-0.position-relative.GO-Shadow-B.GO-Results-Row")

    for vehicle in vehicles:
        # Fetch common elements
        full_name_element = await vehicle.query_selector("div.GO-Results-Naziv span")
        reg_price_element = await query_fallback(vehicle, ["div.GO-Results-Top-Price-TXT-Regular", "div.GO-Results-Price-TXT-Regular"])
        special_price_element = await query_fallback(vehicle, ["div.GO-Results-Top-Price-TXT-AkcijaCena", "div.GO-Results-Price-TXT-AkcijaCena"])
        table_element = await vehicle.query_selector("table.table.table-striped.table-sm.table-borderless.font-weight-normal")
        img_element = await query_fallback(vehicle, ["div.GO-Results-Top-PhotoTop a img", "div.col-auto.p-3.GO-Results-Photo div a img"])
        link_element = await vehicle.query_selector("a.stretched-link")

        full_name = await full_name_element.inner_text() if full_name_element else ""
        name_parts = full_name.strip().split()
        make_value = check_special_make(name_parts)
        specs = await extract_specs_from_table(vehicle, table_element)
        engine_info = specs.get("Motor")

        # Prepare data sources for field processors
        data_sources = {
            "name_parts": name_parts,
            "price": (reg_price_element, special_price_element),
            "specs": specs,
            "engine": engine_info,
            "img_element": img_element,
            "link_element": link_element
        }

        # Build vehicle data dynamically
        vehicle_data = {}
        for field, config in fields.items():
            source = config["source"]
            processor = config["processor"]
            try:
                if source == "name_parts" and field == "model":
                    vehicle_data[field] = processor(name_parts, make_value)
                elif source in data_sources:
                    if source == "price":
                        price_tuple = processor(data_sources[source])
                        vehicle_data[field] = await extract_price(*price_tuple)
                    elif source == "img_element":
                        img = processor(data_sources[source], img_element)
                        vehicle_data[field] = await img.get_attribute('src') if img else None
                    elif source == "link_element":
                        link = processor(data_sources[source], link_element)
                        if link:
                            href = await link.get_attribute('href')
                            vehicle_data[field] = href.replace("..", "https://www.avto.net") if href else None
                        else:
                            vehicle_data[field] = None
                    else:
                        vehicle_data[field] = processor(data_sources[source])
                else:
                    vehicle_data[field] = None
            except Exception as e:
                print(f"Error processing field {field}: {e}")
                vehicle_data[field] = None

        print(vehicle_data)
        await collection.insert_one(vehicle_data)

async def scrape(start_url: str, fields: Dict[str, Dict[str, Any]], collection, start_page: int = 1, end_page: int = 5):
    await collection.delete_many({})

    for i in range(start_page, end_page + 1):
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

            page_url = start_url.replace("stran=1", f"stran={i}")
            try:
                await page.goto(page_url, timeout=60000)
                await page.wait_for_load_state("networkidle")
                await asyncio.sleep(random.uniform(3, 6))
                await scrape_page(page, fields, collection)
            except Exception as e:
                print(f"Error on page {i}: {e}")
                await page.screenshot(path=f"screenshot_error_page_{i}.png")
                await browser.close()
                continue

            await browser.close()
    
    print(f"\nScraping completed.")

# ---------- Helper Functions ----------
async def query_fallback(page, selectors: list[str]):
    for s in selectors:
        element = await page.query_selector(s)
        if element:
            return element
    return None

def check_special_make(name_parts: list[str]) -> Optional[str]:
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

def check_special_model(make: str, name_parts: list[str]) -> Optional[str]:
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
            case "Tesla":
                if name_parts[offset].lower() == "model":
                    return f"{name_parts[offset]} {name_parts[offset+1]}"
                return name_parts[offset]
            case _:
                return name_parts[offset]
    except IndexError:
        return None

async def extract_specs_from_table(vehicle, table_element):
    specs = {}
    if table_element:
        rows = await table_element.query_selector_all("tr")
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
            except Exception as e:
                print(f"Error extracting price: {e}")
                continue
    return None

def extract_engine_info(engine_info, is_motorcycle=False):
    engine_ccm = None
    engine_kw = None
    engine_hp = None
    
    if not engine_info:
        return engine_ccm, engine_kw, engine_hp
    
    engine_info = ' '.join(engine_info.strip().split()).lower()
    
    if is_motorcycle:
        kw_match = re.search(r'(\d+)\s*kw\s*\((\d+)\s*km\)', engine_info)
        if kw_match:
            engine_kw = int(kw_match.group(1))
            engine_hp = int(kw_match.group(2))
        else:
            kw_only = re.search(r'(\d+)\s*kw', engine_info)
            hp_only = re.search(r'(\d+)\s*km', engine_info)
            if kw_only:
                engine_kw = int(kw_only.group(1))
            if hp_only:
                engine_hp = int(hp_only.group(1))
    else:
        parts = [part.strip() for part in engine_info.split(',')]
        
        if parts:
            ccm_match = re.search(r'(\d+)\s*ccm', parts[0])
            if ccm_match:
                engine_ccm = int(ccm_match.group(1))
        
        kw_hp_part = parts[1] if len(parts) > 1 else engine_info
        kw_match = re.search(r'(\d+)\s*kw', kw_hp_part)
        hp_match = re.search(r'(\d+)\s*km', kw_hp_part)
        
        if kw_match:
            engine_kw = int(kw_match.group(1))
        if hp_match:
            engine_hp = int(hp_match.group(1))
    
    return engine_ccm, engine_kw, engine_hp


# ---------- Run the Scraper ----------
if __name__ == "__main__":
    car_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=0&ccmMin=0&ccmMax=99999&mocMin=0&mocMax=999999&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=0&dolzina=&dolzinaMIN=0&dolzinaMAX=100&nosilnostMIN=0&nosilnostMAX=999999&sedezevMIN=0&sedezevMAX=9&lezisc=&presek=0&premer=0&col=0&vijakov=0&EToznaka=0&vozilo=&airbag=&barva=&barvaint=&doseg=0&BkType=0&BkOkvir=0&BkOkvirType=0&Bk4=0&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=1000000020&EQ10=1000000000&KAT=1010000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=0&paketgarancije=&broker=0&prikazkategorije=0&kategorija=0&ONLvid=0&ONLnak=0&zaloga=10&arhiv=0&presort=3&tipsort=DESC&stran=1"
    moto_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=&ccmMin=0&ccmMax=99999&mocMin=&mocMax=&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=&dolzina=&dolzinaMIN=&dolzinaMAX=&nosilnostMIN=&nosilnostMAX=&sedezevMIN=&sedezevMAX=&lezisc=&presek=&premer=&col=&vijakov=&EToznaka=&vozilo=&air calendar=&barva=&barvaint=&doseg=&BkType=&BkOkvir=&BkOkvirType=&Bk4=&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=100000002&EQ10=100000000&KAT=1060000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=&paketgarancije=&broker=&prikazkategorije=&kategorija=61000&ONLvid=&ONLnak=&zaloga=10&arhiv=&presort=&tipsort=&stran=1"
    asyncio.run(scrape(car_url, CAR_FIELDS, car_collection, start_page=1, end_page=1))
    # asyncio.run(scrape(moto_url, MOTORCYCLE_FIELDS, moto_collection, start_page=1, end_page=1))