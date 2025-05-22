import asyncio
from playwright.async_api import async_playwright


async def run():
    url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=&ccmMin=0&ccmMax=99999&mocMin=&mocMax=&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=&motorvalji=&lokacija=0&sirina=&dolzina=&dolzinaMIN=&dolzinaMAX=&nosilnostMIN=&nosilnostMAX=&sedezevMIN=&sedezevMAX=&lezisc=&presek=&premer=&col=&vijakov=&EToznaka=&vozilo=&airbag=&barva=&barvaint=&doseg=&BkType=&BkOkvir=&BkOkvirType=&Bk4=&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=100000002&EQ10=1000000000&KAT=1010000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=&paketgarancije=0&broker=&prikazkategorije=&kategorija=&ONLvid=&ONLnak=&zaloga=10&arhiv=&presort=&tipsort=&stran="

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto(url, timeout=60000)
        await page.wait_for_selector("div.row.bg-white.mb-3.pb-3.pb-sm-0.position-relative.GO-Shadow-B.GO-Results-Row")

        cars = await page.query_selector_all("div.row.bg-white.mb-3.pb-3.pb-sm-0.position-relative.GO-Shadow-B.GO-Results-Row")

        for car in cars:
            make = await car.query_selector("div.GO-Results-Naziv span")
            first_registration = await car.query_selector("table.table.table-striped.table-sm.table-borderless.font-weight-normal.my-3.my-sm-0 tbody tr:first-child td.w-75.pl-3")
            mileage = await car.query_selector("table.table.table-striped.table-sm.table-borderless.font-weight-normal.my-3.my-sm-0 tbody tr:nth-child(2) td.w-75.pl-3")
            price = await car.query_selector(".GO-Results-Top-Price-TXT-Regular")

            print({
                "make": await make.inner_text() if make else None,
                "first_registration": await first_registration.inner_text() if first_registration else None,
                "mileage": await mileage.inner_text() if mileage else None,
                "price": (await price.inner_text()).replace(" €", "") if price else None,
            })

        await browser.close()

asyncio.run(run())