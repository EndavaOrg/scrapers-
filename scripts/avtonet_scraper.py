import requests
import os
from datetime import datetime
from pymongo import MongoClient

# Use MongoDB URI from environment
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise Exception("❌ MONGO_URI is missing in env variables")

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client["primerjalnik_cen_db"]
collection = db["cars"]

# DoberAvto API endpoint
url = "https://www.doberavto.si/internal-api/v1/marketplace/search?results=5000&from=0&includeSold=true&hiddenVin=false"

# Helpers
def translate_transmission(t):
    return {
        "M": "ročni menjalnik",
        "A": "avtomatski menjalnik"
    }.get(t, "neznan")

def translate_fuel(f):
    return {
        "DIESEL": "diesel motor",
        "PETROL": "bencinski motor",
        "ELECTRIC": "električni pogon",
        "HYBRID": "hibridni pogon"
    }.get(f, "neznan")

def extract_year(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").year
    except:
        return None

# Fetch API data
response = requests.get(url)
data = response.json()

# Hold valid links
doberavto_links = set()
new_documents = []

for car in data.get("results", []):
    # Ignore sold cars
    if car.get("postingStatus") == "SOLD":
        continue

    post_id = car.get("postId")
    link = f"https://www.doberavto.si/oglas/{post_id}"
    doberavto_links.add(link)

    # Skip if already exists
    if collection.find_one({"link": link}):
        continue

    # Build the car document
    converted = {
        "make": car.get("manufacturerName"),
        "model": car.get("modelName"),
        "first_registration": extract_year(car.get("registrationDate")),
        "mileage_km": car.get("odometer"),
        "fuel_type": translate_fuel(car.get("fuelType")),
        "gearbox": translate_transmission(car.get("transmission")),
        "engine_ccm": car.get("engineDisplacement"),
        "engine_kw": car.get("enginePower"),
        "engine_hp": round(car.get("enginePower") * 1.36) if car.get("enginePower") else None,
        "battery_kwh": None,
        "state": "RABLJENO" if car.get("historySource") == "USED" else "NOVO",
        "price_eur": car.get("price"),
        "image_url": car.get("imageUrl"),
        "link": link
    }

    new_documents.append(converted)

# Insert new cars
if new_documents:
    collection.insert_many(new_documents)
    print(f"✅ Inserted {len(new_documents)} new DoberAvto cars.")
else:
    print("ℹ️ No new DoberAvto cars to insert.")

deleted_count = 0
cursor = collection.find({"link": {"$regex": "^https://www\\.doberavto\\.si/oglas/"}})

for doc in cursor:
    if doc["link"] not in doberavto_links:
        collection.delete_one({"_id": doc["_id"]})
        deleted_count += 1

print(f"🗑️ Deleted {deleted_count} old DoberAvto cars no longer listed.")
