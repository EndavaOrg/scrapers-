import requests
import os
from datetime import datetime
from pymongo import MongoClient

MONGO_URI = os.getenv("MONGO_URI")

if not MONGO_URI:
    raise Exception("❌ MONGO_URI not found in environment variables")

url = "https://m.autolina.ch/api/v2/searchcars?offset=20&limit=20"

def translate_transmission(t):
    return {
        1201: "Automatic",
        1202: "Manual"
    }.get(t, "Unknown")

def translate_fuel(f):
    return {
        1501: "Petrol",
        1502: "Diesel",
        1503: "Electric",
        1504: "Hybrid"
    }.get(f, "Unknown")

def extract_year(constructionYear):
    try:
        return int(constructionYear)
    except:
        return None

client = MongoClient(MONGO_URI)
db = client["endava"]  
collection = db["cars"]

response = requests.get(url)
data = response.json()

autolina_links = set()
new_documents = []

for car in data.get("data", {}).get("cars", []):
    link = f"https://www.autolina.ch/auto/{car.get('slug')}/{car.get('carId')}"
    autolina_links.add(link)

    if not collection.find_one({"link": link}):
        converted = {
            "make": car.get("makeName"),
            "model": car.get("modelName"),
            "first_registration": extract_year(car.get("constructionYear")),
            "mileage_km": car.get("mileage"),
            "fuel_type": translate_fuel(car.get("fuelType")),
            "gearbox": translate_transmission(car.get("gearboxType")),
            "engine_ccm": None,
            "engine_kw": car.get("powerOutput"),
            "engine_hp": round(car.get("powerOutput") * 1.36) if car.get("powerOutput") else None,
            "battery_kwh": None,
            "state": "NOVO" if car.get("isNew") else "RABLJENO",
            "price_eur": car.get("price"),
            "image_url": car.get("pics")[0] if car.get("pics") else None,
            "link": link
        }
        new_documents.append(converted)

if new_documents:
    collection.insert_many(new_documents)
    print(f"✅ Inserted {len(new_documents)} new Autolina cars.")
else:
    print("ℹ️ No new Autolina cars to insert.")

deleted_count = 0
cursor = collection.find({"link": {"$regex": "^https://www\\.autolina\\.ch/auto/"}})

for doc in cursor:
    if doc["link"] not in autolina_links:
        collection.delete_one({"_id": doc["_id"]})
        deleted_count += 1

print(f"🗑️ Deleted {deleted_count} old Autolina cars no longer listed.")
