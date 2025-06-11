import pytest
import asyncio
from unittest.mock import AsyncMock, Mock
from scripts.avtonet_scraper import (
    scrape_data, check_special_make, check_special_model,
    extract_specs_from_table, extract_price, extract_engine_info,
    CAR_FIELDS
)
import mongomock

@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")

@pytest.mark.asyncio
async def test_scrape_data(mocker):
    # Mock Playwright page and elements
    mock_page = AsyncMock()
    mock_vehicle = AsyncMock()
    mock_full_name_element = AsyncMock()
    mock_reg_price_element = AsyncMock()
    mock_table_element = AsyncMock()
    mock_img_element = AsyncMock()
    mock_link_element = AsyncMock()

    # Mock query selectors
    mock_page.query_selector_all.return_value = [mock_vehicle]
    async def query_selector(selector):
        selector_map = {
            "div.GO-Results-Naziv span": mock_full_name_element,
            "div.GO-Results-Top-Price-TXT-Regular": mock_reg_price_element,
            "div.GO-Results-Top-Price-TXT-AkcijaCena": None,
            "div.GO-Results-Price-TXT-AkcijaCena": None,
            "table.table.table-striped.table-sm.table-borderless.font-weight-normal": mock_table_element,
            "div.GO-Results-Top-PhotoTop a img": mock_img_element,
            "div.col-auto.p-3.GO-Results-Photo div a img": None,
            "a.stretched-link": mock_link_element
        }
        return selector_map.get(selector, None)  # Return None for unexpected selectors

    mock_vehicle.query_selector.side_effect = query_selector

    # Mock query_fallback
    async def mock_query_fallback(vehicle, selectors):
        for selector in selectors:
            element = await query_selector(selector)
            if element:
                return element
        return None

    mocker.patch("scripts.avtonet_scraper.query_fallback", new=mock_query_fallback)

    # Mock element attributes and text
    mock_full_name_element.inner_text.return_value = "BMW Serija 3"
    mock_reg_price_element.inner_text.return_value = "25.000 €"
    mock_table_element.query_selector_all.return_value = [
        AsyncMock(query_selector_all=AsyncMock(return_value=[
            AsyncMock(inner_text=AsyncMock(return_value="1.registracija")),
            AsyncMock(inner_text=AsyncMock(return_value="2020"))
        ])),
        AsyncMock(query_selector_all=AsyncMock(return_value=[
            AsyncMock(inner_text=AsyncMock(return_value="Prevoženih")),
            AsyncMock(inner_text=AsyncMock(return_value="50.000 km"))
        ])),
        AsyncMock(query_selector_all=AsyncMock(return_value=[
            AsyncMock(inner_text=AsyncMock(return_value="Gorivo")),
            AsyncMock(inner_text=AsyncMock(return_value="Bencin"))
        ])),
        AsyncMock(query_selector_all=AsyncMock(return_value=[
            AsyncMock(inner_text=AsyncMock(return_value="Motor")),
            AsyncMock(inner_text=AsyncMock(return_value="2000 ccm, 150 kW (204 KM)"))
        ]))
    ]
    mock_img_element.get_attribute.return_value = "https://example.com/image.jpg"
    mock_link_element.get_attribute.return_value = "../details/123"

    # Mock MongoDB collection
    mock_collection = mongomock.MongoClient().db.collection
    mocker.patch("scripts.avtonet_scraper.car_collection", mock_collection)
    mocker.patch.object(mock_collection, "find_one", return_value=None)  # Mock find_one for mongomock
    mocker.patch.object(mock_collection, "insert_many", return_value=None)  # Mock insert_many for mongomock

    # Mock page URL to avoid RuntimeWarning
    mock_page.url = "https://example.com/stran=1"

    # Run scrape_data
    result = await scrape_data(mock_page, CAR_FIELDS, mock_collection)

    # Assertions
    assert len(result) == 1
    assert result[0]["make"] == "BMW"
    assert result[0]["model"] == "Serija 3"
    assert result[0]["price_eur"] == 25000
    assert result[0]["first_registration"] == 2020
    assert result[0]["mileage_km"] == 50000, f"Expected mileage_km to be 50000, got {result[0]['mileage_km']}"
    assert result[0]["fuel_type"] == "Bencin"
    assert result[0]["engine_ccm"] == 2000
    assert result[0]["engine_kw"] == 150
    assert result[0]["engine_hp"] == 204
    assert result[0]["image_url"] == "https://example.com/image.jpg"
    assert result[0]["link"] == "https://www.avto.net/details/123"

def test_check_special_make():
    # Test multi-word makes
    assert check_special_make(["Land", "Rover", "Discovery"]) == "Land Rover"
    assert check_special_make(["Alfa", "Romeo", "Giulia"]) == "Alfa Romeo"
    assert check_special_make(["BMW", "Serija", "3"]) == "BMW"
    assert check_special_make([]) == None
    assert check_special_make(["Toyota"]) == "Toyota"

def test_check_special_model():
    assert check_special_model("BMW", ["BMW", "Serija", "3"]) == "Serija 3"
    assert check_special_model("Land Rover", ["Land", "Rover", "Range", "Rover"]) == "Range Rover"
    assert check_special_model("Tesla", ["Tesla", "Model", "S"]) == "Model S"
    assert check_special_model("Toyota", ["Toyota", "Corolla"]) == "Corolla"
    assert check_special_model("BMW", ["BMW"]) == None
    assert check_special_model("BMW", []) == None

@pytest.mark.asyncio
async def test_extract_specs_from_table():
    # Mock table element and rows
    mock_table = AsyncMock()
    mock_row1 = AsyncMock()
    mock_row2 = AsyncMock()
    mock_table.query_selector_all.return_value = [mock_row1, mock_row2]
    mock_row1.query_selector_all.return_value = [
        AsyncMock(inner_text=AsyncMock(return_value="1.registracija")),
        AsyncMock(inner_text=AsyncMock(return_value="2020"))
    ]
    mock_row2.query_selector_all.return_value = [
        AsyncMock(inner_text=AsyncMock(return_value="Gorivo")),
        AsyncMock(inner_text=AsyncMock(return_value="Bencin"))
    ]

    specs = await extract_specs_from_table(AsyncMock(), mock_table)
    assert specs == {"1.registracija": "2020", "Gorivo": "Bencin"}

@pytest.mark.asyncio
async def test_extract_price():
    # Mock price elements
    mock_reg_price = AsyncMock()
    mock_reg_price.inner_text.return_value = "25.000 €"
    mock_special_price = AsyncMock()
    mock_special_price.inner_text.return_value = "20.000 €"

    # Test regular price
    price = await extract_price(mock_reg_price, None)
    assert price == 25000

    # Test special price
    price = await extract_price(None, mock_special_price)
    assert price == 20000

    # Test invalid price
    mock_invalid_price = AsyncMock()
    mock_invalid_price.inner_text.return_value = "Negotiable"
    price = await extract_price(mock_invalid_price, None)
    assert price == None

def test_extract_engine_info():
    # Test car engine info
    engine_info = "2000 ccm, 150 kW (204 KM)"
    ccm, kw, hp = extract_engine_info(engine_info, is_motorcycle=False)
    assert ccm == 2000
    assert kw == 150
    assert hp == 204

    # Test motorcycle engine info
    engine_info = "100 kW (136 KM)"
    ccm, kw, hp = extract_engine_info(engine_info, is_motorcycle=True)
    assert ccm == None
    assert kw == 100
    assert hp == 136

    # Test invalid engine info
    ccm, kw, hp = extract_engine_info("", is_motorcycle=False)
    assert ccm == None
    assert kw == None
    assert hp == None