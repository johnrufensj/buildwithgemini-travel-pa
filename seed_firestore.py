"""
Firestore Seeding Script for Travel PA
Project ID is hardcoded as required for Agent Platform compatibility.
"""

import subprocess
import google.auth
from google.oauth2 import credentials
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-01-6188783eec72"
COLLECTION_NAME = "travel_spots"

SEED_SPOTS = [
    {
        "spot_id": "sf-001",
        "name": "Golden Gate Bridge",
        "city": "San Francisco",
        "country": "USA",
        "category": "Sightseeing",
        "description": "Iconic red suspension bridge connecting San Francisco Bay to Marin County.",
        "rating": 4.8,
        "estimated_cost_usd": 0.0,
        "tags": ["landmark", "photography", "outdoors", "iconic"],
    },
    {
        "spot_id": "sf-002",
        "name": "Ferry Building Marketplace",
        "city": "San Francisco",
        "country": "USA",
        "category": "Food & Dining",
        "description": "Historic food hall featuring artisan food vendors, local eateries, and a farmers market.",
        "rating": 4.7,
        "estimated_cost_usd": 25.0,
        "tags": ["foodie", "local market", "shopping"],
    },
    {
        "spot_id": "che-001",
        "name": "Marina Beach",
        "city": "Chennai",
        "country": "India",
        "category": "Nature & Parks",
        "description": "One of the longest natural urban beaches in the world, famous for sunset strolls and street food.",
        "rating": 4.6,
        "estimated_cost_usd": 5.0,
        "tags": ["beach", "sunset", "street food", "local culture"],
    },
    {
        "spot_id": "che-002",
        "name": "Kapaleeshwarar Temple",
        "city": "Chennai",
        "country": "India",
        "category": "Culture & History",
        "description": "7th-century Dravidian architecture temple dedicated to Lord Shiva in Mylapore.",
        "rating": 4.9,
        "estimated_cost_usd": 0.0,
        "tags": ["heritage", "architecture", "spiritual"],
    },
    {
        "spot_id": "tok-001",
        "name": "Senso-ji Temple",
        "city": "Tokyo",
        "country": "Japan",
        "category": "Culture & History",
        "description": "Ancient Buddhist temple located in Asakusa, Tokyo's oldest temple.",
        "rating": 4.8,
        "estimated_cost_usd": 0.0,
        "tags": ["temple", "history", "asakusa"],
    },
    {
        "spot_id": "tok-002",
        "name": "Tsukiji Outer Market",
        "city": "Tokyo",
        "country": "Japan",
        "category": "Food & Dining",
        "description": "Bustling market packed with sushi stalls, fresh seafood, and Japanese culinary tools.",
        "rating": 4.7,
        "estimated_cost_usd": 30.0,
        "tags": ["sushi", "street food", "seafood"],
    }
]


def get_firestore_client():
    """Returns a Firestore client, using local gcloud token fallback if needed."""
    try:
        token = subprocess.check_output(['gcloud', 'auth', 'print-access-token'], text=True).strip()
        creds = credentials.Credentials(token)
        return firestore.Client(project=PROJECT_ID, credentials=creds)
    except Exception:
        return firestore.Client(project=PROJECT_ID)


def seed_database():
    db = get_firestore_client()
    print(f"Connecting to Firestore for project: '{PROJECT_ID}'...")
    collection_ref = db.collection(COLLECTION_NAME)

    for item in SEED_SPOTS:
        doc_id = item["spot_id"]
        collection_ref.document(doc_id).set(item)
        print(f"  - Seeded spot: {item['name']} ({item['city']}) [{doc_id}]")

    print(f"✅ Seeding complete! {len(SEED_SPOTS)} items seeded into '{COLLECTION_NAME}'.")


if __name__ == "__main__":
    seed_database()
