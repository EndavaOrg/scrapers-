# Vehicle Scraper with Playwright

This project is a web scraper built using [Playwright](https://playwright.dev/python/) and [Playwright Stealth](https://github.com/AtSymbolDev/playwright-stealth) to collect vehicle listing data from [avto.net](https://www.avto.net/). The scraped data is saved to a MongoDB database.

---

## Features

- Web scraping using Playwright
- Stealth plugin to bypass bot detection
- Asynchronous scraping with `asyncio`
- MongoDB integration using `motor`
- `.env` support for easy configuration

---

## Base requirements

- Python 3.8 or later
- pip (Python package manager)
- MongoDB instance running (local or remote)

---

## Installation

### 1. Clone the repository

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv
```

### 3. Activate the virtual environment

#### Windows (Command Prompt):
```bash
venv\Scripts\activate
```

#### Windows (Powershell):
```bash
.\venv\Scripts\Activate.ps1
```

#### MacOS/Linux
```bash
source venv/bin/activate
```

### 4. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Install Playwright browsers

```bash
python -m playwright install
```

---

## Configuration

Create a .env file in the project root with the following content:

```bash
MONGO_URI=your-mongo-uri
DB_NAME=your-db-name
COLLECTIONS=your-collections-comma-separated
```
Update the values as needed to match your MongoDB setup.

## Running the scraper/s

Run the scraper/s using:

```bash
python file_name.py
```

## Notes

To run in headless mode, change the launch() line in the script:

```python
browser = await p.chromium.launch(headless=True)
```

Data is stored in MongoDB and can be queried using any MongoDB client.