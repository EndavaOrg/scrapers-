import pytest
import asyncio
from unittest.mock import AsyncMock, Mock
import random
from scripts.avtonet_scraper import (
    scrape_single_page,
    create_batches,
    scrape,
    scrape_data,
    CAR_FIELDS
)
import mongomock
from playwright.async_api import async_playwright, Playwright

@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")

@pytest.fixture
def mock_playwright(mocker):
    class AsyncContextManagerMock:
        def __init__(self):
            self.chromium = AsyncMock()
            self.browser = AsyncMock()
            self.context = AsyncMock()
            self.page = AsyncMock()
            self.chromium.launch.return_value = self.browser
            self.browser.new_context.return_value = self.context
            self.context.new_page.return_value = self.page
            self.page.goto.return_value = AsyncMock(status=200)
            self.page.wait_for_load_state.return_value = None
            self.page.context = self.context  # Ensure stealth_async compatibility

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_playwright_instance = AsyncContextManagerMock()
    mocker.patch("scripts.avtonet_scraper.async_playwright", return_value=mock_playwright_instance)
    return mock_playwright_instance, mock_playwright_instance.page, mock_playwright_instance.context, mock_playwright_instance.browser

# @pytest.mark.asyncio
# async def test_scrape_single_page_success(mocker, mock_playwright):
#     # Unpack Playwright mocks
#     mock_playwright_instance, mock_page, mock_context, mock_browser = mock_playwright
    
#     # Mock dependencies
#     mock_collection = mongomock.MongoClient().db.collection
#     start_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=0&ccmMin=0&ccmMax=99999&mocMin=0&mocMax=999999&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=0&dolzina=&dolzinaMIN=0&dolzinaMAX=100&nosilnostMIN=0&nosilnostMAX=999999&sedezevMIN=0&sedezevMAX=9&lezisc=&presek=0&premer=0&col=0&vijakov=0&EToznaka=0&vozilo=&airbag=&barva=&barvaint=&doseg=0&BkType=0&BkOkvir=0&BkOkvirType=0&Bk4=0&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=1000000020&EQ10=1000000000&KAT=1010000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=0&paketgarancije=&broker=0&prikazkategorije=0&kategorija=0&ONLvid=0&ONLnak=0&zaloga=10&arhiv=0&presort=3&tipsort=DESC&stran=1"
#     page_num = 2
#     expected_data = [{"make": "BMW", "model": "Serija 3"}]
#     mock_scrape_data = mocker.patch(
#         "scripts.avtonet_scraper.scrape_data",
#         new=AsyncMock(return_value=expected_data)
#     )
    
#     # Mock stealth_async
#     mock_stealth_async = mocker.patch(
#         "scripts.avtonet_scraper.stealth_async",
#         new=AsyncMock(return_value=None)
#     )
    
#     # Mock random.uniform for deterministic testing
#     mocker.patch("random.uniform", return_value=1.5)
    
#     # Mock print for debugging
#     mock_print = mocker.patch("builtins.print")
    
#     # Run scrape_single_page
#     result = await scrape_single_page(
#         page_num=page_num,
#         context=mock_context,
#         start_url=start_url,
#         fields=CAR_FIELDS,
#         collection=mock_collection,
#         scrape_data_func=scrape_data
#     )
    
#     # Assertions
#     expected_url = start_url.replace("stran=1", f"stran={page_num}")
#     assert result == expected_data, f"Expected vehicle data {expected_data}, got {result}"
#     mock_page.goto.assert_called_once_with(expected_url, timeout=30000)
#     mock_page.wait_for_load_state.assert_called_once_with("domcontentloaded", timeout=30000)
#     mock_scrape_data.assert_called_once_with(mock_page, CAR_FIELDS, mock_collection)
#     mock_stealth_async.assert_called_once_with(mock_page)
#     mock_page.close.assert_called_once()
#     mock_print.assert_any_call(f"Scraping page {page_num}...")
#     mock_print.assert_any_call(f"Page {page_num} status: 200")
#     # Check for unexpected error prints
#     for call in mock_print.call_args_list:
#         assert "Debug: Exception in scrape_single_page" not in str(call), f"Unexpected exception: {call}"

@pytest.mark.asyncio
async def test_scrape_single_page_error(mocker, mock_playwright):
    # Unpack Playwright mocks
    mock_playwright_instance, mock_page, mock_context, mock_browser = mock_playwright
    
    # Mock dependencies
    mock_collection = mongomock.MongoClient().db.collection
    start_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=0&ccmMin=0&ccmMax=99999&mocMin=0&mocMax=999999&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=0&dolzina=&dolzinaMIN=0&dolzinaMAX=100&nosilnostMIN=0&nosilnostMAX=999999&sedezevMIN=0&sedezevMAX=9&lezisc=&presek=0&premer=0&col=0&vijakov=0&EToznaka=0&vozilo=&airbag=&barva=&barvaint=&doseg=0&BkType=0&BkOkvir=0&BkOkvirType=0&Bk4=0&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=1000000020&EQ10=1000000000&KAT=1010000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=0&paketgarancije=&broker=0&prikazkategorije=0&kategorija=0&ONLvid=0&ONLnak=0&zaloga=10&arhiv=0&presort=3&tipsort=DESC&stran=1"
    page_num = 2
    
    # Simulate page.goto failure
    mock_page.goto.side_effect = Exception("Network error")
    mock_screenshot = mocker.patch.object(mock_page, "screenshot", new=AsyncMock())
    
    # Mock stealth_async
    mocker.patch("scripts.avtonet_scraper.stealth_async", new=AsyncMock(return_value=None))
    
    # Mock print for debugging
    mock_print = mocker.patch("builtins.print")
    
    # Run scrape_single_page
    result = await scrape_single_page(
        page_num=page_num,
        context=mock_context,
        start_url=start_url,
        fields=CAR_FIELDS,
        collection=mock_collection,
        scrape_data_func=scrape_data
    )
    
    # Assertions
    expected_url = start_url.replace("stran=1", f"stran={page_num}")
    assert result == [], f"Expected empty list on error, got {result}"
    mock_page.goto.assert_called_once_with(expected_url, timeout=30000)
    mock_screenshot.assert_called_once_with(path=f"screenshot_error_page_{page_num}.png")
    mock_page.close.assert_called_once()
    mock_print.assert_any_call(f"Scraping page {page_num}...")
    # Check for debug exception print with flexible matching
    debug_print_found = any(
        "Debug: Exception in scrape_single_page" in str(call) and "Network error" in str(call)
        for call in mock_print.call_args_list
    )
    assert debug_print_found, f"Expected debug print with 'Network error', got {mock_print.call_args_list}"

def test_create_batches():
    # Test normal batch creation
    batches = create_batches(start_page=1, end_page=10, batch_size=3)
    expected = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10]]
    assert batches == expected, f"Expected {expected}, got {batches}"
    
    # Test single page
    batches = create_batches(start_page=1, end_page=1, batch_size=3)
    assert batches == [[1]], f"Expected [[1]], got {batches}"
    
    # Test empty range
    batches = create_batches(start_page=1, end_page=0, batch_size=3)
    assert batches == [], f"Expected [], got {batches}"
    
    # Test partial batch
    batches = create_batches(start_page=1, end_page=4, batch_size=5)
    assert batches == [[1, 2, 3, 4]], f"Expected [[1, 2, 3, 4]], got {batches}"

@pytest.mark.asyncio
async def test_scrape(mocker, mock_playwright):
    # Unpack Playwright mocks
    mock_playwright_instance, mock_page, mock_context, mock_browser = mock_playwright
    
    # Mock dependencies
    mock_collection = mongomock.MongoClient().db.collection
    start_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=0&ccmMin=0&ccmMax=99999&mocMin=0&mocMax=999999&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=0&dolzina=&dolzinaMIN=0&dolzinaMAX=100&nosilnostMIN=0&nosilnostMAX=999999&sedezevMIN=0&sedezevMAX=9&lezisc=&presek=0&premer=0&col=0&vijakov=0&EToznaka=0&vozilo=&airbag=&barva=&barvaint=&doseg=0&BkType=0&BkOkvir=0&BkOkvirType=0&Bk4=0&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=1000000020&EQ10=1000000000&KAT=1010000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=0&paketgarancije=&broker=0&prikazkategorije=0&kategorija=0&ONLvid=0&ONLnak=0&zaloga=10&arhiv=0&presort=3&tipsort=DESC&stran=1"
    start_page = 1
    end_page = 3
    batch_size = 2
    
    # Mock create_batches
    mock_create_batches = mocker.patch(
        "scripts.avtonet_scraper.create_batches",
        return_value=[[1, 2], [3]]
    )
    
    # Mock scrape_single_page
    mock_scrape_single_page = mocker.patch(
        "scripts.avtonet_scraper.scrape_single_page",
        new=AsyncMock(return_value=[{"make": "BMW"}])
    )
    
    # Mock scrape_data
    mocker.patch("scripts.avtonet_scraper.scrape_data", new=AsyncMock())
    
    # Mock print for debugging
    mock_print = mocker.patch("builtins.print")
    
    # Run scrape
    await scrape(
        start_url=start_url,
        fields=CAR_FIELDS,
        collection=mock_collection,
        start_page=start_page,
        end_page=end_page,
        batch_size=batch_size,
        scrape_data_func=scrape_data,
        create_batches_func=mock_create_batches,
        scrape_single_page_func=mock_scrape_single_page
    )
    
    # Assertions
    mock_create_batches.assert_called_once_with(start_page, end_page, batch_size)
    assert mock_scrape_single_page.call_count == 3, f"Expected 3 calls to scrape_single_page, got {mock_scrape_single_page.call_count}"
    expected_calls = [
        mocker.call(1, mock_context, start_url, CAR_FIELDS, mock_collection, scrape_data),
        mocker.call(2, mock_context, start_url, CAR_FIELDS, mock_collection, scrape_data),
        mocker.call(3, mock_context, start_url, CAR_FIELDS, mock_collection, scrape_data)
    ]
    mock_scrape_single_page.assert_has_calls(expected_calls, any_order=True)
    mock_browser.new_context.assert_called_with(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 720},
        locale="en-US"
    )
    mock_context.close.assert_called()
    mock_browser.close.assert_called()
    mock_print.assert_any_call(f"Processing 2 batches of up to {batch_size} pages each.")
    mock_print.assert_any_call(f"\nStarting batch: pages 1 to 2")
    mock_print.assert_any_call(f"Closed browser for batch: pages 1 to 2")
    mock_print.assert_any_call(f"\nStarting batch: pages 3 to 3")
    mock_print.assert_any_call(f"Closed browser for batch: pages 3 to 3")

# @pytest.mark.asyncio
# async def test_scrape_single_page_retry(mocker, mock_playwright):
#     # Unpack Playwright mocks
#     mock_playwright_instance, mock_page, mock_context, mock_browser = mock_playwright
    
#     # Mock dependencies
#     mock_collection = mongomock.MongoClient().db.collection
#     start_url = "https://www.avto.net/Ads/results.asp?znamka=&model=&modelID=&tip=&znamka2=&model2=&tip2=&znamka3=&model3=&tip3=&cenaMin=0&cenaMax=999999&letnikMin=0&letnikMax=2090&bencin=0&starost2=999&oblika=0&ccmMin=0&ccmMax=99999&mocMin=0&mocMax=999999&kmMin=0&kmMax=9999999&kwMin=0&kwMax=999&motortakt=0&motorvalji=0&lokacija=0&sirina=0&dolzina=&dolzinaMIN=0&dolzinaMAX=100&nosilnostMIN=0&nosilnostMAX=999999&sedezevMIN=0&sedezevMAX=9&lezisc=&presek=0&premer=0&col=0&vijakov=0&EToznaka=0&vozilo=&airbag=&barva=&barvaint=&doseg=0&BkType=0&BkOkvir=0&BkOkvirType=0&Bk4=0&EQ1=1000000000&EQ2=1000000000&EQ3=1000000000&EQ4=100000000&EQ5=1000000000&EQ6=1000000000&EQ7=1110100120&EQ8=101000000&EQ9=1000000020&EQ10=1000000000&KAT=1010000000&PIA=&PIAzero=&PIAOut=&PSLO=&akcija=0&paketgarancije=&broker=0&prikazkategorije=0&kategorija=0&ONLvid=0&ONLnak=0&zaloga=10&arhiv=0&presort=3&tipsort=DESC&stran=1"
#     page_num = 2
#     expected_data = [{"make": "BMW"}]
    
#     # Simulate page.goto failure for first two attempts, success on third
#     mock_response = AsyncMock(status=200)
#     mock_page.goto.side_effect = [Exception("Network error"), Exception("Network error"), mock_response]
#     mock_screenshot = mocker.patch.object(mock_page, "screenshot", new=AsyncMock())
#     mock_scrape_data = mocker.patch(
#         "scripts.avtonet_scraper.scrape_data",
#         new=AsyncMock(return_value=expected_data)
#     )
    
#     # Mock stealth_async
#     mocker.patch("scripts.avtonet_scraper.stealth_async", new=AsyncMock(return_value=None))
    
#     # Mock random.uniform
#     mocker.patch("random.uniform", return_value=1.5)
    
#     # Mock print for debugging
#     mock_print = mocker.patch("builtins.print")
    
#     # Run scrape_single_page
#     result = await scrape_single_page(
#         page_num=page_num,
#         context=mock_context,
#         start_url=start_url,
#         fields=CAR_FIELDS,
#         collection=mock_collection,
#         scrape_data_func=scrape_data
#     )
    
#     # Assertions
#     expected_url = start_url.replace("stran=1", f"stran={page_num}")
#     assert result == expected_data, f"Expected vehicle data {expected_data}, got {result}"
#     assert mock_page.goto.call_count == 3, f"Expected 3 goto calls (2 retries + 1 success), got {mock_page.goto.call_count}"
#     assert mock_screenshot.call_count == 2, f"Expected 2 screenshots for failed attempts, got {mock_screenshot.call_count}"
#     mock_scrape_data.assert_called_once_with(mock_page, CAR_FIELDS, mock_collection)
#     mock_page.close.assert_called_once()
#     mock_print.assert_any_call(f"Scraping page {page_num}...")
#     mock_print.assert_any_call(f"Debug: Exception in scrape_single_page: Exception: Network error")
#     mock_print.assert_any_call(f"Page {page_num} status: 200")