import asyncio
import random
import warnings

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from motor.motor_asyncio import AsyncIOMotorClient
from cryptography.utils import CryptographyDeprecationWarning

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

MONGO_URI = "mongodb+srv://leomasevski:leomasevskiPassword@cluster0.dt5en3h.mongodb.net/primerjalnik_cen_db?retryWrites=true&w=majority"
DB_NAME = "primerjalnik_cen_db"
COLLECTION_NAME = "cars"

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
cars_collection = db[COLLECTION_NAME]


async def scrape_page(page):
    # Wait for results to appear
    await page.wait_for_selector("div.row.bg-white.mb-3.pb-3.pb-sm-0.position-relative.GO-Shadow-B.GO-Results-Row", timeout=60000)

    cars = await page.query_selector_all("div.row.bg-white.mb-3.pb-3.pb-sm-0.position-relative.GO-Shadow-B.GO-Results-Row")

    for car in cars:
        full_name_element = await car.query_selector("div.GO-Results-Naziv span") # Car make element
        reg_price_element = await car.query_selector("div.GO-Results-Top-Price-TXT-Regular") # Car regular price element
        special_price_element = await car.query_selector("div.GO-Results-Top-Price-TXT-AkcijaCena") # Car special price element
        # image_element = TODO
        # link_element = TODO

        full_name = await full_name_element.inner_text() if full_name_element else "" # Car full name
        name_parts = full_name.strip().split()

        # Extract make and model parts
        make_value = name_parts[0] if len(name_parts) > 0 else None
        model_value = check_special_model(make_value, name_parts)

        # Extract specs
        table = await car.query_selector("table.table.table-striped.table-sm.table-borderless.font-weight-normal.my-3.my-sm-0")
        specs = {}
        if table:
            rows = await table.query_selector_all("tr")
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) == 2:
                    key = (await cells[0].inner_text()).strip()
                    value = (await cells[1].inner_text()).strip()
                    specs[key] = value

        # Extract price
        price_value = await extract_price(reg_price_element, special_price_element)

        # Extract engine information
        engine_ccm_value, engine_kw_value = extract_engine_info(specs.get("Motor"))

        # Extract first reg, mileage, battery
        first_reg_value, mileage_value, battery_value = None, None, None
        first_reg_value = int(specs.get("1.registracija").strip()) if specs.get("1.registracija") else None
        mileage_value = int(specs.get("Prevoženih").replace(" km", "").strip()) if specs.get("Prevoženih") else None
        battery_value = float(specs.get("Baterija").replace(" kWh", "").replace(",", ".").strip()) if specs.get("Baterija") else None

        # Car Data
        car_data = {
            "make": make_value,
            "model": model_value,
            "price": price_value,
            "first_registration": first_reg_value,
            "mileage": mileage_value,
            "fuel_type": specs.get("Gorivo"),
            "gearbox": specs.get("Menjalnik"),
            "engine_ccm": engine_ccm_value,
            "engine_kw": engine_kw_value,
            "battery": battery_value,
            "age": specs.get("Starost")
        }

        print(car_data)
        await cars_collection.insert_one(car_data)


async def run():
    await cars_collection.delete_many({})

    start_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=0&ccmMin=0&ccmMax=99999&mocMin=0&mocMax=999999&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=0&dolzina=&dolzinaMIN=0&dolzinaMAX=100&nosilnostMIN=0&nosilnostMAX=999999&sedezevMIN=0&sedezevMAX=9&lezisc=&presek=0&premer=0&col=0&vijakov=0&EToznaka=0&vozilo=&airbag=&barva=&barvaint=&doseg=0&BkType=0&BkOkvir=0&BkOkvirType=0&Bk4=0&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=1000000020&EQ10=1000000000&KAT=1010000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=0&paketgarancije=&broker=0&prikazkategorije=0&kategorija=0&ONLvid=0&ONLnak=0&zaloga=10&arhiv=0&presort=3&tipsort=DESC&stran=1"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US"
        )

        page = await context.new_page()
        await stealth_async(page)
        await page.goto(start_url)

        for i in range(1, 3):
            print(f"\nScraping page {i}...")
            try:
                await scrape_page(page)
            except Exception as e:
                print(f"Error scraping page {i}: {e}")

            try:
                # Find the "Naprej" button and click it
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1000)  # Wait for any dynamic loading
                next_button = await page.query_selector('li.page-item.GO-Rounded-R a.page-link:has-text("Naprej")')
                if next_button:
                    await next_button.click()
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(random.uniform(3, 6))  # Delay
                else:
                    print("No next button found, ending scraping.")
                    break
            except Exception as e:
                print(f"Failed to click next page: {e}")
                break

        await browser.close()


# ---------- Helper functions ----------
def check_special_model(make: str, name_parts: list[str]) -> str | None:
    match make:
        case "BMW":
            second = name_parts[1] if len(name_parts) > 1 else ""
            third = name_parts[2] if len(name_parts) > 2 else ""
            if second.lower() == "serija":
                return f"{second} {third}"
            else:
                return second if second else None
        case _:
            return name_parts[1] if len(name_parts) > 1 else None

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

    if engine_info:
        parts = engine_info.strip().split()
        try:
            engine_ccm = int(parts[0])
        except (IndexError, ValueError):
            pass
        try:
            engine_kw = int(parts[2])
        except (IndexError, ValueError):
            pass

    return engine_ccm, engine_kw


# Run the scraper
asyncio.run(run())