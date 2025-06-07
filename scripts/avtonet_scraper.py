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
from tenacity import retry, stop_after_attempt, wait_exponential

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")
COLLECTIONS = os.getenv("COLLECTIONS", "").split(",")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
car_collection = db[COLLECTIONS[0]]
moto_collection = db[COLLECTIONS[1]]
truck_collection = db[COLLECTIONS[2]]

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

TRUCK_FIELDS = {
    "make": {"source": "name_parts", "processor": lambda np: check_special_make(np)},
    "model": {"source": "name_parts", "processor": lambda np, make: check_special_model(make, np)},
    "price_eur": {"source": "price", "processor": lambda price_tuple: price_tuple},
    "Year": {"source": "specs", "processor": lambda s: int(s.get("Letnik").strip()) if s.get("Letnik") else None},
    "mileage_km": {"source": "specs", "processor": lambda s: int(s.get("Prevoženih").replace(" km", "").strip()) if s.get("Prevoženih") else None},
    "fuel_type": {"source": "specs", "processor": lambda s: s.get("Gorivo")},
    "gearbox": {"source": "specs", "processor": lambda s: s.get("Menjalnik")},
    "state": {"source": "specs", "processor": lambda s: s.get("Starost") if s.get("Starost") else "RABLJENO"},
    "image_url": {"source": "img_element", "processor": lambda img, _: img},
    "link": {"source": "link_element", "processor": lambda _, link: link}
}

async def scrape_data(page, fields: Dict[str, Dict[str, Any]], collection) -> list:
    vehicles = await page.query_selector_all("div.row.bg-white.position-relative.GO-Results-Row.GO-Shadow-B, div.row.bg-white.mb-3.pb-3.pb-sm-0.position-relative.GO-Shadow-B.GO-Results-Row")
    vehicle_data_list = []

    for vehicle in vehicles:
        full_name_element = await vehicle.query_selector("div.GO-Results-Naziv span")
        reg_price_element = await query_fallback(vehicle, ["div.GO-Results-Top-Price-TXT-Regular", "div.GO-Results-Price-TXT-AkcijaCena"])
        special_price_element = await query_fallback(vehicle, ["div.GO-Results-Top-Price-TXT-AkcijaCena", "div.GO-Results-Price-TXT-AkcijaCena"])
        table_element = await vehicle.query_selector("table.table.table-striped.table-sm.table-borderless.font-weight-normal")
        img_element = await query_fallback(vehicle, ["div.GO-Results-Top-PhotoTop a img", "div.col-auto.p-3.GO-Results-Photo div a img"])
        link_element = await vehicle.query_selector("a.stretched-link")

        full_name = await full_name_element.inner_text() if full_name_element else ""
        name_parts = full_name.strip().split()
        make_value = check_special_make(name_parts)
        specs = await extract_specs_from_table(vehicle, table_element)
        engine_info = specs.get("Motor")

        data_sources = {
            "name_parts": name_parts,
            "price": (reg_price_element, special_price_element),
            "specs": specs,
            "engine": engine_info,
            "img_element": img_element,
            "link_element": link_element
        }

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

        # Skip if no valid link or if vehicle already exists in the database
        if vehicle_data.get("link"):
            existing_vehicle = await collection.find_one({"link": vehicle_data["link"]})
            if existing_vehicle:
                continue  # Skip if vehicle already exists
            if any(vehicle_data.values()):  # Only add if there's some valid data
                vehicle_data_list.append(vehicle_data)

    if vehicle_data_list:
        try:
            await collection.insert_many(vehicle_data_list, ordered=False)
            print(f"Inserted {len(vehicle_data_list)} new vehicles from page {page.url.split('=')[-1]}")
        except Exception as e:
            print(f"Error inserting data to MongoDB: {e}")

    return vehicle_data_list

# ==================== REUSABLE FUNCTIONS ====================
async def cleanup_outdated_vehicles(collection):
    async with async_playwright() as p:
        try:
            cursor = collection.find({}, {"link": 1})
            links = [doc["link"] async for doc in cursor]
            print(f"Checking {len(links)} vehicle links for validity")
            invalid_links = []

            batch_size = 30
            for i in range(0, len(links), batch_size):
                batch_links = links[i:i + batch_size]
                print(f"Processing batch of {len(batch_links)} links (links {i+1} to {i+len(batch_links)})")
                
                browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 720},
                    locale="en-US"
                )

                tasks = [check_vehicle_page_validity(context, link) for link in batch_links]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for link, is_valid in zip(batch_links, results):
                    print(f"Checked link: {link}, Valid: {is_valid}")
                    if not is_valid:
                        invalid_links.append(link)

                await context.close()
                await browser.close()
                print(f"Closed browser for batch {i//batch_size + 1}")
                
            if invalid_links:
                result = await collection.delete_many({"link": {"$in": invalid_links}})
                print(f"Removed {result.deleted_count} outdated vehicles with invalid links from the database")
            else:
                print("No outdated vehicles found to remove")
        except Exception as e:
            print(f"Error during cleanup of outdated vehicles: {e}")

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
async def check_vehicle_page_validity(context, link: str) -> bool:
    page = await context.new_page()
    await stealth_async(page)
    try:
        response = await page.goto(link, timeout=20000)
        if response.status != 200:
            print(f"Invalid status code {response.status} for link: {link}")
            return False
        content = await page.content()
        error_message = "Oglas je že odstranjen iz ponudbe.".lower()
        if error_message in content.lower():
            print(f"Error message '{error_message}' found for link: {link}")
            return False
        vehicle_title_element = await page.query_selector("div.col-12.mt-3.pt-1")
        if not vehicle_title_element:
            print(f"No vehicle title found for link: {link}")
            return False
        return True
    except Exception as e:
        print(f"Error checking link {link}: {e}")
        return False
    finally:
        await page.close()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def scrape_single_page(page_num: int, context, start_url: str, fields: Dict[str, Dict[str, Any]], collection, scrape_data_func):
    print(f"Scraping page {page_num}...")
    page = await context.new_page()
    await stealth_async(page)

    page_url = start_url.replace("stran=1", f"stran={page_num}").replace("currentPage=1", f"currentPage={page_num}")
    try:
        response = await page.goto(page_url, timeout=30000)
        print(f"Page {page_num} status: {response.status}")
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(random.uniform(1.0, 2.5))
        vehicle_data = await scrape_data_func(page, fields, collection)
        return vehicle_data
    except Exception as e:
        print(f"Error on page {page_num}: {e}")
        await page.screenshot(path=f"screenshot_error_page_{page_num}.png")
        return []
    finally:
        await page.close()

def create_batches(start_page: int, end_page: int, batch_size: int):
    pages = list(range(start_page, end_page + 1))
    return [pages[i:i + batch_size] for i in range(0, len(pages), batch_size)]

async def scrape(start_url: str, fields: Dict[str, Dict[str, Any]], collection, start_page, end_page, batch_size, scrape_data_func, create_batches_func=create_batches, scrape_single_page_func=scrape_single_page, cleanup_outdated_vehicles_func=cleanup_outdated_vehicles):
    async with async_playwright() as p:
        page_batches = create_batches_func(start_page, end_page, batch_size)
        print(f"Processing {len(page_batches)} batches of up to {batch_size} pages each.")

        for batch in page_batches:
            print(f"\nStarting batch: pages {batch[0]} to {batch[-1]}")
            browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="en-US"
            )
            tasks = [scrape_single_page_func(page_num, context, start_url, fields, collection, scrape_data_func) for page_num in batch]
            await asyncio.gather(*tasks, return_exceptions=True)
            await context.close()
            await browser.close()
            print(f"Closed browser for batch: pages {batch[0]} to {batch[-1]}")

    await cleanup_outdated_vehicles_func(collection)
    print(f"\nScraping completed.")

# ==================== HELPER FUNCTIONS ====================
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
                if not price_text.replace(" ", "").isdigit():
                    return None
                return int(price_text)
            except Exception as e:
                print(f"Error extracting price: {e}")
                continue
    return None

def extract_engine_info(engine_info, is_motorcycle=False):
    if not engine_info:
        return None, None, None
    engine_info = ' '.join(engine_info.strip().split()).lower()
    engine_ccm, engine_kw, engine_hp = None, None, None
    if is_motorcycle:
        match = re.search(r'(\d+)\s*kw\s*\((\d+)\s*km\)', engine_info)
        if match:
            engine_kw, engine_hp = int(match.group(1)), int(match.group(2))
        else:
            engine_kw = next((int(m.group(1)) for m in [re.search(r'(\d+)\s*kw', engine_info)] if m), None)
            engine_hp = next((int(m.group(1)) for m in [re.search(r'(\d+)\s*km', engine_info)] if m), None)
    else:
        parts = engine_info.split(',')
        if parts:
            engine_ccm = next((int(m.group(1)) for m in [re.search(r'(\d+)\s*ccm', parts[0])] if m), None)
        kw_hp_part = parts[1] if len(parts) > 1 else engine_info
        engine_kw = next((int(m.group(1)) for m in [re.search(r'(\d+)\s*kw', kw_hp_part)] if m), None)
        engine_hp = next((int(m.group(1)) for m in [re.search(r'(\d+)\s*km', kw_hp_part)] if m), None)
    return engine_ccm, engine_kw, engine_hp

# ==================== RUN THE SCRAPERS ====================
if __name__ == "__main__":
    car_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=0&ccmMin=0&ccmMax=99999&mocMin=0&mocMax=999999&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=0&dolzina=&dolzinaMIN=0&dolzinaMAX=100&nosilnostMIN=0&nosilnostMAX=999999&sedezevMIN=0&sedezevMAX=9&lezisc=&presek=0&premer=0&col=0&vijakov=0&EToznaka=0&vozilo=&airbag=&barva=&barvaint=&doseg=0&BkType=0&BkOkvir=0&BkOkvirType=0&Bk4=0&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=1000000020&EQ10=1000000000&KAT=1010000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=0&paketgarancije=&broker=0&prikazkategorije=0&kategorija=0&ONLvid=0&ONLnak=0&zaloga=10&arhiv=0&presort=3&tipsort=DESC&stran=1"
    moto_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=&ccmMin=0&ccmMax=99999&mocMin=&mocMax=&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=&dolzina=&dolzinaMIN=&dolzinaMAX=&nosilnostMIN=&nosilnostMAX=&sedezevMIN=&sedezevMAX=&lezisc=&presek=&premer=&col=&vijakov=&EToznaka=&vozilo=&aircalendar=&barva=&barvaint=&doseg=&BkType=&BkOkvir=&BkOkvirType=&Bk4=&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=100000002&EQ10=100000000&KAT=1060000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=&paketgarancije=&broker=&prikazkategorije=&kategorija=61000&ONLvid=&ONLnak=&zaloga=10&arhiv=&presort=&tipsort=&stran=1"
    truck_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=41&ccmMin=&ccmMax=&mocMin=&mocMax=&kmMin=0&kmMax=9999999&kwMin=0&kwMax=9999&motortakt=&motorvalji=&lokacija=0&sirina=&dolzina=&dolzinaMIN=&dolzinaMAX=&nosilnostMIN=&nosilnostMAX=&sedezevMIN=&sedezevMAX=&lezisc=&presek=&premer=&col=&vijakov=&EToznaka=&vozilo=&airbag=&barva=&barvaint=&doseg=&BkType=&BkOkvir=&BkOkvirType=&Bk4=&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=100000002&EQ10=100000000&KAT=1040000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=&paketgarancije=&broker=&prikazkategorije=&kategorija=0&ONLvid=&ONLnak=&zaloga=10&arhiv=&presort=&tipsort=&stran=1"

    asyncio.run(scrape(
        start_url=car_url,
        fields=CAR_FIELDS,
        collection=car_collection,
        start_page=1,
        end_page=25,
        batch_size=5,
        scrape_data_func=scrape_data
    ))