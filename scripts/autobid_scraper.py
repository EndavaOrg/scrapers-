import asyncio
import warnings
import os
import re

from typing import Dict, Any
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from motor.motor_asyncio import AsyncIOMotorClient
from cryptography.utils import CryptographyDeprecationWarning
from tenacity import retry, stop_after_attempt, wait_exponential
from avtonet_scraper import scrape, scrape_single_page, create_batches, check_special_make, check_special_model

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

mongo_uri = os.environ.get("MONGO_URI")
if not mongo_uri:
    raise RuntimeError("MONGO_URI not set in environment variables.")

client = AsyncIOMotorClient(mongo_uri)
db = client["primerjalnik_cen_db"]
car_collection = db["cars"]
moto_collection = db["motorcycles"]
truck_collection = db["trucks"]

FUEL_TYPES = {
    "bencin", "dizel", "avtoplin", "zemeljski plin", "hibrid", 
    "mild-hybrid", "plug-in-hybrid", "benzin mildhybrid", 
    "diesel mildhybrid", "diesel plugin hybrid", "električno vozilo", "ethanol"
}
GEARBOX_TYPES = {
    "4-stopenjsko stikalno gonilo", "5-stopenjsko stikalno gonilo", 
    "6-stopenjsko stikalno gonilo", "7-stopenjsko stikalno gonilo", 
    "avtomatik", "polavtomatik", "ročni menjalnik"
}

VEHICLE_FIELDS = {
    "make": {"source": "name_parts", "processor": lambda np: check_special_make(np)},
    "model": {"source": "name_parts", "processor": lambda np, make: check_special_model(make, np)},
    "price_eur": {"source": "price", "processor": lambda price: price},
    "first_registration": {
        "source": "specs",
        "processor": lambda s: int(s[0].split(".")[-1].strip()) if s and s[0] and re.match(r"\d{1,2}\.\d{4}", s[0]) else None
    },
    "mileage_km": {
        "source": "specs",
        "processor": lambda s: int(s[1].replace(" Kilometrih", "").replace(".", "").strip()) if s and len(s) > 1 and "Kilometrih" in s[1] else None
    },
    "fuel_type": {
        "source": "misc",
        "processor": lambda m: next((item.strip() for item in m.split(", ") if item.strip().lower() in FUEL_TYPES), None) if m else None
    },
    "gearbox": {
        "source": "misc",
        "processor": lambda m: next((item.strip() for item in m.split(", ") if item.strip().lower() in GEARBOX_TYPES), None) if m else None
    },
    "engine_kw": {
        "source": "specs",
        "processor": lambda s: int(re.search(r"(\d+)\s*kW", s[2]).group(1)) if s and len(s) > 2 and re.search(r"(\d+)\s*kW", s[2]) else None
    },
    "engine_hp": {
        "source": "specs",
        "processor": lambda s: int(re.search(r"(\d+)\s*KM", s[2]).group(1)) if s and len(s) > 2 and re.search(r"(\d+)\s*KM", s[2]) else None
    },
    "state": {
        "source": "specs",
        "processor": lambda s: (
            "RABLJENO" if s and len(s) > 3 and s[3] and (
                s[3].lower().startswith("neznano") or 
                (re.search(r"^\s*(\d+)\s*(?:lastnik|lastnikov)?\s*$", s[3]) and 
                int(re.search(r"^\s*(\d+)\s*(?:lastnik|lastnikov)?\s*$", s[3]).group(1)) > 0)
            ) else "NOVO"
        )
    },
    "image_url": {"source": "img_element", "processor": lambda img, _: img},
    "link": {"source": "link_element", "processor": lambda _, link: link}
}

async def scrape_data(page, fields: Dict[str, Dict[str, Any]], collection):
    vehicles = await page.query_selector_all("div.-mx-3.block.px-3.pt-3.cursor-pointer")
    vehicle_data_list = []

    for vehicle in vehicles:
        full_name_element = await vehicle.query_selector("a.relative.max-w-max")
        price_element = await vehicle.query_selector("div.flex.w-full.flex-col.xl\\:mt-0.xl\\:w-auto.md\\:w-1\\/4.hidden.md\\:flex span span span")
        specs_elements = await vehicle.query_selector_all("span.car-parameter-value.w-full.sm\\:w-auto")
        misc_element = await vehicle.query_selector("p.mt-4")
        img_element = await vehicle.query_selector("picture.flex.h-auto.w-full.max-w-full.object-contain img")
        link_element = await vehicle.query_selector("a.flex.w-full.min-w-full.items-center.justify-center.bg-black")

        full_name = await full_name_element.inner_text() if full_name_element else ""
        name_parts = full_name.strip().split()
        specs_values = await extract_specs_from_spans(specs_elements)
        misc_text = await misc_element.inner_text() if misc_element else ""
        if misc_text and "drugo" in misc_text.lower():
            continue
        make_value = check_special_make(name_parts) if name_parts else None

        data_sources = {
            "name_parts": name_parts,
            "price": price_element,
            "specs": specs_values,
            "misc": misc_text,
            "img_element": img_element,
            "link_element": link_element
        }

        vehicle_data = {}
        for field, config in fields.items():
            source = config["source"]
            processor = config["processor"]
            try:
                if source == "name_parts" and field == "model":
                    vehicle_data[field] = processor(name_parts, make_value) if name_parts and make_value else None
                elif source == "price":
                    price = await extract_price(data_sources[source])
                    vehicle_data[field] = processor(price) if price is not None else None
                elif source == "img_element":
                        img = processor(data_sources[source], img_element)
                        vehicle_data[field] = await img.get_attribute('src') if img else None
                elif source == "link_element":
                    link = processor(data_sources[source], link_element)
                    if link:
                        href = await link.get_attribute('href')
                        vehicle_data[field] = "https://autobid.de" + href  if href else None
                    else:
                        vehicle_data[field] = None
                else:
                    vehicle_data[field] = processor(data_sources[source]) if data_sources[source] else None
            except Exception as e:
                print(f"Error processing field {field}: {e}")
                vehicle_data[field] = None

        if vehicle_data.get("link"):
            existing_vehicle = await collection.find_one({"link": vehicle_data["link"]})
            if existing_vehicle:
                continue
            if any(vehicle_data.values()):
                vehicle_data_list.append(vehicle_data)

    if vehicle_data_list:
        try:
            await collection.insert_many(vehicle_data_list, ordered=False)
            print(f"Inserted {len(vehicle_data_list)} new vehicles from page {page.url.split('=')[-1]}")
        except Exception as e:
            print(f"Error inserting data to MongoDB: {e}")

    return vehicle_data_list

# ---------- Helper Functions ----------
async def extract_specs_from_spans(specs_elements):
    specs_values = []
    for element in specs_elements:
        value = await element.inner_text() if element else ""
        specs_values.append(value.strip())
    return specs_values

async def extract_price(price_element):
    if price_element:
        try:
            price_value = await price_element.inner_text()
            price_value = price_value.replace("\xa0", "").replace("€", "").replace(".", "").replace(",", "").strip()
            return int(price_value) if price_value.isdigit() else None
        except Exception as e:
            print(f"Error extracting price: {e}")
    return None

async def scrape_all_categories():
    await scrape(
        start_url=car_url,
        fields=VEHICLE_FIELDS,
        collection=car_collection,
        start_page=1,
        end_page=25,
        batch_size=5,
        scrape_data_func=scrape_data
    )
    await scrape(
        start_url=moto_url,
        fields=VEHICLE_FIELDS,
        collection=moto_collection,
        start_page=1,
        end_page=25,
        batch_size=5,
        scrape_data_func=scrape_data
    )
    await scrape(
        start_url=truck_url,
        fields=VEHICLE_FIELDS,
        collection=truck_collection,
        start_page=1,
        end_page=25,
        batch_size=5,
        scrape_data_func=scrape_data
    )

if __name__ == "__main__":
    car_url = "https://autobid.de/sl/rezultati-iskanja?e367=1&sortingType=auctionStartDate-DESCENDING&currentPage=1"
    moto_url = "https://autobid.de/sl/rezultati-iskanja?e367=2&sortingType=auctionStartDate-DESCENDING&currentPage=1"
    truck_url = "https://autobid.de/sl/rezultati-iskanja?e367=3&sortingType=auctionStartDate-DESCENDING&currentPage=1"

    asyncio.run(scrape_all_categories())