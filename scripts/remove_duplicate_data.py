import asyncio
import os
import sys
import logging

from motor.motor_asyncio import AsyncIOMotorClient

# Configure logging for GitHub Actions
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

mongo_uri = os.environ.get("MONGO_URI")
if not mongo_uri:
    raise RuntimeError("MONGO_URI not set in environment variables.")

client = AsyncIOMotorClient(mongo_uri)
db = client["endava"]
car_collection = db["cars"]
moto_collection = db["motorcycles"]
truck_collection = db["trucks"]

async def remove_duplicate_links(collection, site_name: str, semaphore: asyncio.Semaphore):
    async with semaphore:  # Limit concurrent operations
        try:
            logger.info(f"Checking for duplicate links in collection: {collection.name}, site: {site_name}")
            
            # Aggregate to find duplicate links
            pipeline = [
                {"$match": {"link": {"$regex": site_name}}},  # Filter by site_name
                {"$group": {
                    "_id": "$link",
                    "count": {"$sum": 1},
                    "ids": {"$push": "$_id"}
                }},
                {"$match": {"count": {"$gt": 1}}}  # Find links with count > 1
            ]
            
            duplicates = await collection.aggregate(pipeline).to_list(length=None)
            logger.info(f"Found {len(duplicates)} links with duplicates in collection: {collection.name}, site: {site_name}")
            
            for duplicate in duplicates:
                link = duplicate["_id"]
                ids = duplicate["ids"]
                count = duplicate["count"]
                
                # Keep the first ID, remove the rest
                ids_to_remove = ids[1:]  # Skip the first ID
                if ids_to_remove:
                    result = await collection.delete_many({"_id": {"$in": ids_to_remove}})
                    logger.info(f"Removed {result.deleted_count} duplicate entries for link: {link} (kept 1, removed {count-1}) in collection: {collection.name}")
            
            logger.info(f"Completed duplicate removal for collection: {collection.name}, site: {site_name}")
        except Exception as e:
            logger.error(f"Error during duplicate removal for {site_name}, collection: {collection.name}: {e}")

async def cleanup_duplicate_links_all_collections(site_name: str):
    semaphore = asyncio.Semaphore(3)  # Limit to 3 concurrent operations
    collections = [car_collection, moto_collection, truck_collection]
    logger.info(f"Starting concurrent duplicate cleanup for all collections with site: {site_name}")
    tasks = [remove_duplicate_links(collection, site_name, semaphore) for collection in collections]
    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info(f"Completed duplicate cleanup for all collections with site: {site_name}")

async def cleanup_duplicate_links_all_sites():
    await cleanup_duplicate_links_all_collections("avto.net")
    await cleanup_duplicate_links_all_collections("autobid.de")

if __name__ == "__main__":
    asyncio.run(cleanup_duplicate_links_all_sites())