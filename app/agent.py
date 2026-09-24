# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import os
import subprocess
import uuid
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

import google.auth
from google.oauth2 import credentials
from google.cloud import firestore, storage
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.memory import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.adk.tools.load_memory_tool import LoadMemoryTool
from google.genai import types

from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog
from .a2ui_utils import a2ui_callback

PROJECT_ID = "qwiklabs-gcp-01-6188783eec72"
COLLECTION_NAME = "travel_spots"
BUCKET_NAME = "travel-pa-media-qwiklabs-gcp-01-6188783eec72"
MEMORY_ENGINE_ID = "9115138311239761920"


def _load_env_file():
    """Helper to load key-value pairs from .env if present in environment."""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


def _get_db_client():
    """Helper to return a Firestore Client for the hardcoded project ID."""
    try:
        token = subprocess.check_output(['gcloud', 'auth', 'print-access-token'], text=True).strip()
        creds = credentials.Credentials(token)
        return firestore.Client(project=PROJECT_ID, credentials=creds)
    except Exception:
        return firestore.Client(project=PROJECT_ID)


def _get_storage_client():
    """Helper to return a Storage Client for the hardcoded project ID."""
    try:
        token = subprocess.check_output(['gcloud', 'auth', 'print-access-token'], text=True).strip()
        creds = credentials.Credentials(token)
        return storage.Client(project=PROJECT_ID, credentials=creds)
    except Exception:
        return storage.Client(project=PROJECT_ID)


def _get_sandbox_code_executor():
    """Helper to instantiate AgentEngineSandboxCodeExecutor using deployment_metadata.json if available."""
    metadata_path = os.path.join(os.path.dirname(__file__), "..", "deployment_metadata.json")
    agent_engine_id = None
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, "r") as f:
                meta = json.load(f)
                agent_engine_id = meta.get("remote_agent_runtime_id")
        except Exception:
            pass

    if agent_engine_id:
        return AgentEngineSandboxCodeExecutor(agent_engine_resource_name=agent_engine_id)
    return AgentEngineSandboxCodeExecutor()


# Memory service instance for future redeployments
memory_service = VertexAiMemoryBankService(
    project=PROJECT_ID,
    location="us-east1",
    agent_engine_id=MEMORY_ENGINE_ID
)


async def generate_memories_callback(callback_context: CallbackContext):
    """Sends session events to Memory Bank after conversation turns for long-term memory generation."""
    await callback_context.add_session_to_memory()
    return None


def generate_spot_image(
    prompt: str,
    filename: str = "travel_spot.jpg",
    tool_context: ToolContext = None
) -> str:
    """Generates an image for a travel destination using gemini-3.1-flash-lite-image model in the global region.

    Saves the image into the Playground Artifacts panel via tool_context.save_artifact, and uploads
    the image bytes directly to public Cloud Storage, returning its public HTTPS URL.

    Args:
        prompt: Visual prompt describing the travel destination or scene to generate (e.g., 'A vibrant sunset view over Marina Beach in Chennai').
        filename: Optional output filename for the image artifact (default 'travel_spot.jpg').
        tool_context: ADK ToolContext instance passed automatically by the agent framework.

    Returns:
        A string containing the public HTTPS URL of the generated image in Cloud Storage.
    """
    try:
        from google import genai

        # 1. Generate image using gemini-3.1-flash-lite-image in the global region
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt
        )

        image_bytes = None
        mime_type = "image/jpeg"
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or mime_type
                    break

        if not image_bytes:
            return f"Failed to generate image for prompt: '{prompt}'."

        # Clean filename extension
        if not filename.endswith((".jpg", ".jpeg", ".png")):
            ext = ".png" if "png" in mime_type else ".jpg"
            filename = f"{filename}{ext}"

        # 2. Save artifact to Playground's Artifacts panel using tool_context.save_artifact
        if tool_context is not None:
            part_artifact = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            tool_context.save_artifact(filename=filename, artifact=part_artifact)

        # 3. Upload image bytes directly to public Cloud Storage bucket (no local file writing)
        storage_client = _get_storage_client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
        return f"Successfully generated image and uploaded to public Cloud Storage: {public_url}"

    except Exception as e:
        return f"Error generating travel spot image: {str(e)}"


def generate_spot_video(
    prompt: str,
    filename: str = "travel_spot.mp4",
    tool_context: ToolContext = None
) -> str:
    """Generates a short video for a travel spot or destination using Google's Omni model (gemini-omni-flash-preview) in the global region.

    Saves the video into the Playground Artifacts panel via tool_context.save_artifact, and uploads
    the video bytes directly to public Cloud Storage, returning its public HTTPS URL.

    Args:
        prompt: Description of the travel destination or scene to generate a video for (e.g., 'A scenic drone view over the Golden Gate Bridge at sunset').
        filename: Optional output filename for the video artifact (default 'travel_spot.mp4').
        tool_context: ADK ToolContext instance passed automatically by the agent framework.

    Returns:
        A string containing the public HTTPS URL of the generated video in Cloud Storage.
    """
    try:
        import base64
        from google import genai
        from google.genai._gaos.types.interactions import VideoDelta

        # 1. Generate video using gemini-omni-flash-preview via Interactions API in global region
        client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
        events = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
            stream=True
        )

        video_chunks = []
        mime_type = "video/mp4"

        for event in events:
            if hasattr(event, "delta") and isinstance(event.delta, VideoDelta):
                vd = event.delta
                if vd.data:
                    if isinstance(vd.data, str):
                        video_chunks.append(base64.b64decode(vd.data))
                    else:
                        video_chunks.append(vd.data)
                if vd.mime_type:
                    mime_type = vd.mime_type

        video_bytes = b"".join(video_chunks)
        if not video_bytes:
            return f"Failed to generate video for prompt: '{prompt}'."

        # Clean filename extension
        if not filename.endswith((".mp4", ".webm", ".mov")):
            filename = f"{filename}.mp4"

        # 2. Save artifact to Playground's Artifacts panel using tool_context.save_artifact
        if tool_context is not None:
            part_artifact = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
            tool_context.save_artifact(filename=filename, artifact=part_artifact)

        # 3. Upload video bytes directly to public Cloud Storage bucket (no local file writing)
        storage_client = _get_storage_client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type=mime_type)

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
        return f"Successfully generated video and uploaded to public Cloud Storage: {public_url}"

    except Exception as e:
        return f"Error generating travel spot video: {str(e)}"



def geocode_address(address: str) -> dict:
    """Turns an address or location name into geographic coordinates (latitude, longitude) using Google Maps Geocoding API.

    Args:
        address: The address, city, or landmark name to geocode (e.g., 'Eiffel Tower, Paris', '1600 Amphitheatre Pkwy, Mountain View, CA').

    Returns:
        A dictionary containing key fields: 'name', 'address', and 'location' (latitude, longitude).
    """
    _load_env_file()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return {"error": "GOOGLE_MAPS_API_KEY environment variable is not set."}

    try:
        encoded_address = urllib.parse.quote(address)
        url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"
        req = urllib.request.Request(url, headers={"User-Agent": "TravelPA/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        if data.get("status") != "OK" or not data.get("results"):
            msg = data.get("error_message") or data.get("status") or "No results found"
            return {"error": f"Geocoding failed for '{address}': {msg}"}

        result = data["results"][0]
        formatted_address = result.get("formatted_address", address)
        loc = result.get("geometry", {}).get("location", {})

        return {
            "name": address,
            "address": formatted_address,
            "location": {
                "latitude": loc.get("lat"),
                "longitude": loc.get("lng")
            }
        }
    except Exception as e:
        return {"error": f"Error during geocoding: {str(e)}"}


def find_nearby_places(latitude: float, longitude: float, place_type: str = "restaurant", radius_meters: float = 1000.0) -> list[dict]:
    """Finds nearby places of a given type around a coordinate location using Google Places API (New).

    Args:
        latitude: Latitude coordinate of central location (e.g. 37.7749).
        longitude: Longitude coordinate of central location (e.g. -122.4194).
        place_type: Type of place to search for (e.g. 'restaurant', 'tourist_attraction', 'museum', 'cafe', 'park').
        radius_meters: Search radius in meters (default 1000.0).

    Returns:
        A list of place dictionaries containing key fields: 'name', 'address', and 'location'.
    """
    _load_env_file()
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return [{"error": "GOOGLE_MAPS_API_KEY environment variable is not set."}]

    try:
        url = "https://places.googleapis.com/v1/places:searchNearby"
        payload = json.dumps({
            "includedTypes": [place_type],
            "maxResultCount": 5,
            "locationRestriction": {
                "circle": {
                    "center": {
                        "latitude": latitude,
                        "longitude": longitude
                    },
                    "radius": radius_meters
                }
            }
        }).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location"
        }

        req = urllib.request.Request(url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        places = data.get("places", [])
        results = []
        for p in places:
            display_name = p.get("displayName", {}).get("text", "Unknown Place")
            formatted_addr = p.get("formattedAddress", "")
            loc = p.get("location", {})
            results.append({
                "name": display_name,
                "address": formatted_addr,
                "location": {
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude")
                }
            })

        return results if results else [{"message": f"No nearby places of type '{place_type}' found."}]
    except Exception as e:
        return [{"error": f"Error searching nearby places: {str(e)}"}]


def get_live_weather(city: str) -> str:
    """Fetches real-time live weather data for any global city using Open-Meteo API.

    Args:
        city: The city name to check live weather for (e.g., 'Paris', 'Tokyo', 'Chennai', 'San Francisco').

    Returns:
        A formatted string with live temperature, humidity, and wind speed.
    """
    try:
        encoded_city = urllib.parse.quote(city)
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded_city}&count=1&language=en&format=json"
        req = urllib.request.Request(geo_url, headers={"User-Agent": "TravelPA/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            geo_data = json.loads(response.read().decode())

        if not geo_data.get("results"):
            return f"Could not find location coordinates for '{city}'."

        loc = geo_data["results"][0]
        lat, lon = loc["latitude"], loc["longitude"]
        city_name = loc.get("name", city)
        country = loc.get("country", "")

        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,wind_speed_10m"
        req_w = urllib.request.Request(weather_url, headers={"User-Agent": "TravelPA/1.0"})
        with urllib.request.urlopen(req_w, timeout=5) as resp_w:
            w_data = json.loads(resp_w.read().decode())

        current = w_data.get("current", {})
        temp_c = current.get("temperature_2m")
        humidity = current.get("relative_humidity_2m")
        wind_kph = current.get("wind_speed_10m")

        temp_f = round(temp_c * 9 / 5 + 32, 1) if temp_c is not None else "N/A"

        return (
            f"Live weather for {city_name}, {country}: "
            f"Temperature: {temp_c}°C ({temp_f}°F), Humidity: {humidity}%, Wind Speed: {wind_kph} km/h."
        )
    except Exception as e:
        return f"Error fetching live weather for {city}: {str(e)}"


def convert_currency(amount: float, from_currency: str = "USD", to_currency: str = "EUR") -> str:
    """Converts a monetary amount between currencies using real-time rates from the Frankfurter API.

    Args:
        amount: The numerical amount of money to convert (e.g., 100.0, 250.50).
        from_currency: 3-letter source currency code (e.g., 'USD', 'EUR', 'GBP', 'INR', 'JPY').
        to_currency: 3-letter target currency code (e.g., 'EUR', 'USD', 'INR', 'JPY', 'GBP').

    Returns:
        A formatted string detailing the conversion result and rate.
    """
    try:
        from_curr = from_currency.upper().strip()
        to_curr = to_currency.upper().strip()

        if from_curr == to_curr:
            return f"{amount:.2f} {from_curr} is equal to {amount:.2f} {to_curr}."

        api_key = os.environ.get("FRANKFURTER_API_KEY", os.environ.get("CURRENCY_API_KEY", ""))

        url = f"https://api.frankfurter.app/latest?amount={amount}&from={from_curr}&to={to_curr}"
        req = urllib.request.Request(url, headers={"User-Agent": "TravelPA/1.0"})
        if api_key:
            req.add_header("Authorization", f"Bearer {api_key}")

        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())

        rates = data.get("rates", {})
        converted_val = rates.get(to_curr)
        if converted_val is None:
            return f"Could not find exchange rate from {from_curr} to {to_curr}."

        rate = converted_val / amount if amount != 0 else 0.0
        return (
            f"{amount:.2f} {from_curr} = {converted_val:.2f} {to_curr} "
            f"(Exchange rate: 1 {from_curr} = {rate:.4f} {to_curr} as of {data.get('date', 'latest')})."
        )
    except Exception as e:
        return f"Error converting currency from {from_currency} to {to_currency}: {str(e)}"


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    query_lower = query.lower()
    if "sf" in query_lower or "san francisco" in query_lower:
        tz_identifier = "America/Los_Angeles"
    elif "chennai" in query_lower or "keerapakkam" in query_lower or "india" in query_lower:
        tz_identifier = "Asia/Kolkata"
    else:
        tz_identifier = "UTC"

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


def search_travel_spots(city: str = "", category: str = "") -> list[dict]:
    """Searches the travel spots catalog in Firestore by city or category.

    Args:
        city: Optional city name (e.g. 'San Francisco', 'Chennai', 'Tokyo').
        category: Optional category (e.g. 'Sightseeing', 'Food & Dining', 'Nature & Parks', 'Culture & History').

    Returns:
        A list of matching travel spot dictionaries.
    """
    db = _get_db_client()
    collection_ref = db.collection(COLLECTION_NAME)
    docs = collection_ref.stream()

    results = []
    for doc in docs:
        data = doc.to_dict()
        if city and city.lower() not in data.get("city", "").lower():
            continue
        if category and category.lower() not in data.get("category", "").lower():
            continue
        results.append(data)

    return results


def add_travel_spot(
    spot_id: str,
    name: str,
    city: str,
    country: str,
    category: str,
    description: str,
    rating: float = 4.5,
    estimated_cost_usd: float = 0.0,
    tags: str = "sightseeing"
) -> str:
    """Adds a new travel spot to the Firestore catalog.

    Args:
        spot_id: Unique ID for the spot (e.g., 'par-001').
        name: Name of the attraction or spot.
        city: City where the spot is located.
        country: Country where the spot is located.
        category: Category ('Sightseeing', 'Food & Dining', 'Nature & Parks', 'Culture & History').
        description: Detailed summary of the spot.
        rating: Rating out of 5.0 (default 4.5).
        estimated_cost_usd: Estimated cost in USD (default 0.0).
        tags: Comma-separated tags (e.g. 'museum, art, iconic').

    Returns:
        A success message string.
    """
    db = _get_db_client()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    doc_data = {
        "spot_id": spot_id,
        "name": name,
        "city": city,
        "country": country,
        "category": category,
        "description": description,
        "rating": rating,
        "estimated_cost_usd": estimated_cost_usd,
        "tags": tag_list
    }
    db.collection(COLLECTION_NAME).document(spot_id).set(doc_data)
    return f"Successfully saved travel spot '{name}' ({spot_id}) in {city}, {country} to Firestore."


# Build A2UI system instruction using A2uiSchemaManager version 0.8 & BasicCatalog
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Travel PA, an expert personal assistant for travelers. "
        "Help users generate spot images and videos, geocode addresses, find nearby places, discover spots in the catalog, "
        "check live weather, convert currencies, add new places, and execute Python code in a safe sandbox. "
        "You have access to a Memory Bank that remembers information across user sessions. "
        "CRITICAL REQUIREMENT: Always pay strict attention to all user dietary restrictions and allergies "
        "(such as peanut, tree nut, gluten, dairy, or shellfish allergies). Save and remember all user allergies "
        "in long-term memory. Whenever recommending travel spots, food, or nearby places, retrieve remembered "
        "user allergies and filter out any unsafe or conflicting recommendations."
    ),
    workflow_description="Analyze the request and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model="gemini-flash-latest",
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    code_executor=_get_sandbox_code_executor(),
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
    tools=[
        PreloadMemoryTool(),
        LoadMemoryTool(),
        generate_spot_image,
        generate_spot_video,
        geocode_address,
        find_nearby_places,
        get_live_weather,
        convert_currency,
        get_current_time,
        search_travel_spots,
        add_travel_spot
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
)
