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
import logging
import os
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.memory.vertex_ai_memory_bank_service import VertexAiMemoryBankService
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google.genai import types

from .a2ui_utils import a2ui_callback

# CRITICAL: Hardcode project ID string (do not use google.auth.default() or GOOGLE_CLOUD_PROJECT env var)
PROJECT_ID = "qwiklabs-gcp-02-f418aae87c3d"
BUCKET_NAME = "smart-pantry-recipes-qwiklabs-gcp-02-f418aae87c3d"
MEMORY_BANK_ID = "78690947688300544"


def _init_env():
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    key = k.strip()
                    if key not in os.environ:
                        os.environ[key] = v.strip().strip('"\'')

_init_env()


def get_firestore_client():
    from google.cloud import firestore
    return firestore.Client(project=PROJECT_ID)


def get_maps_api_key() -> str:
    """Retrieve Google Maps API Key from environment variable or local .env file."""
    return os.getenv("GOOGLE_MAPS_API_KEY", "")


def memory_bank_service_builder():
    """Build a VertexAiMemoryBankService configured for this agent's Memory Bank instance."""
    return VertexAiMemoryBankService(
        project=PROJECT_ID,
        location="us-east1",
        agent_engine_id=MEMORY_BANK_ID,
    )


async def generate_memories_callback(callback_context: CallbackContext):
    """WRITE callback: After each turn, send the session events to Memory Bank for durable fact extraction."""
    try:
        await callback_context.add_session_to_memory()
    except Exception as e:
        logger.warning(f"Memory Bank service not available: {e}")
    return None


def search_recipes(query: str = "") -> str:
    """Search for recipes in the local Firestore database by keyword (matches name, ingredients, cuisine, or dietary tags).

    Args:
        query: Optional search keyword or ingredient (e.g. 'salmon', 'pasta', 'vegan', 'Italian').

    Returns:
        A list of matching recipe details or a summary of available recipes.
    """
    db = get_firestore_client()
    recipes_ref = db.collection("recipes")
    docs = recipes_ref.stream()

    results = []
    q = query.lower().strip()
    tokens = [t for t in q.replace(" or ", " ").replace(" and ", " ").split() if len(t) > 2]

    for doc in docs:
        data = doc.to_dict()
        if not q or not tokens:
            results.append(data)
        else:
            name = data.get("name", "").lower()
            cuisine = data.get("cuisine", "").lower()
            ingredients = [ing.lower() for ing in data.get("main_ingredients", [])]
            dietary = [tag.lower() for tag in data.get("dietary_tags", [])]

            text_corpus = f"{name} {cuisine} {' '.join(ingredients)} {' '.join(dietary)}"
            if any(t in text_corpus for t in tokens):
                results.append(data)

    if not results:
        return f"No recipes found in database matching query: '{query}'."

    output = [f"Found {len(results)} recipe(s):"]
    for r in results:
        output.append(
            f"- {r.get('name')} (ID: {r.get('id')} | Cuisine: {r.get('cuisine')} | Prep: {r.get('prep_time_mins')}m | Calories: {r.get('calories')})\n"
            f"  Ingredients: {', '.join(r.get('main_ingredients', []))}\n"
            f"  Tags: {', '.join(r.get('dietary_tags', []))}\n"
            f"  Instructions: {r.get('instructions')}"
        )
    return "\n\n".join(output)


def add_recipe(
    name: str,
    main_ingredients: list[str],
    instructions: str,
    prep_time_mins: int = 20,
    cuisine: str = "General",
    dietary_tags: list[str] = None,
    calories: int = 400
) -> str:
    """Add a new recipe to the Firestore database.

    Args:
        name: Name of the recipe (e.g. 'Avocado Toast').
        main_ingredients: List of key ingredients (e.g. ['bread', 'avocado', 'egg']).
        instructions: Preparation / cooking instructions.
        prep_time_mins: Preparation time in minutes.
        cuisine: Cuisine style (e.g. 'American', 'Mexican').
        dietary_tags: List of dietary tags (e.g. ['vegetarian', 'quick']).
        calories: Estimated calorie count per serving.

    Returns:
        A success message with the created recipe ID.
    """
    db = get_firestore_client()
    doc_ref = db.collection("recipes").document()
    recipe_id = doc_ref.id

    data = {
        "id": recipe_id,
        "name": name,
        "prep_time_mins": prep_time_mins,
        "cuisine": cuisine,
        "main_ingredients": main_ingredients,
        "dietary_tags": dietary_tags or [],
        "instructions": instructions,
        "calories": calories,
    }
    doc_ref.set(data)
    return f"Successfully saved recipe '{name}' to Firestore with ID: {recipe_id}."


def calculate_recipe_nutrition(
    calories_per_serving: int,
    protein_g: float,
    carbs_g: float,
    fat_g: float,
    servings: int = 1
) -> str:
    """Calculate scaled nutritional information and macro breakdown for a given number of servings.

    Args:
        calories_per_serving: Calories in one serving of the recipe.
        protein_g: Protein in grams per serving.
        carbs_g: Carbohydrates in grams per serving.
        fat_g: Fat in grams per serving.
        servings: Number of servings to scale for (default is 1).

    Returns:
        A string formatted summary with scaled calories, macro grams, and macro energy percentages.
    """
    if servings <= 0:
        return "Error: Servings must be a positive integer greater than 0."

    total_calories = calories_per_serving * servings
    total_protein = protein_g * servings
    total_carbs = carbs_g * servings
    total_fat = fat_g * servings

    p_cal = total_protein * 4
    c_cal = total_carbs * 4
    f_cal = total_fat * 9
    sum_cal = p_cal + c_cal + f_cal or 1.0

    p_pct = round((p_cal / sum_cal) * 100, 1)
    c_pct = round((c_cal / sum_cal) * 100, 1)
    f_pct = round((f_cal / sum_cal) * 100, 1)

    return (
        f"Nutritional Summary for {servings} serving(s):\n"
        f"- Total Calories: {total_calories} kcal\n"
        f"- Protein: {round(total_protein, 1)}g ({p_pct}% of calories)\n"
        f"- Carbs: {round(total_carbs, 1)}g ({c_pct}% of calories)\n"
        f"- Fat: {round(total_fat, 1)}g ({f_pct}% of calories)"
    )


def search_global_recipes(query: str) -> str:
    """Fetch real recipe ideas and meal suggestions from TheMealDB public API.

    Args:
        query: Name of dish or main ingredient to search globally (e.g. 'chicken', 'pasta', 'tacos').

    Returns:
        A formatted list of real global recipes with cuisine, ingredients, instructions, and image URL.
    """
    if not query or not query.strip():
        return "Please provide a valid recipe name or ingredient query."

    api_key = os.getenv("MEALDB_API_KEY", "1")
    encoded_query = urllib.parse.quote(query.strip())
    url = f"https://www.themealdb.com/api/json/v1/{api_key}/search.php?s={encoded_query}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SmartPantryBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return f"Error connecting to global recipe API: {e}"

    meals = data.get("meals")
    if not meals:
        return f"No global recipes found matching '{query}' on TheMealDB."

    results = []
    for meal in meals[:3]:
        name = meal.get("strMeal")
        area = meal.get("strArea", "International")
        category = meal.get("strCategory", "Main")
        instructions = meal.get("strInstructions", "").strip()
        if len(instructions) > 250:
            instructions = instructions[:250] + "..."
        image_url = meal.get("strMealThumb")

        ingredients = []
        for i in range(1, 21):
            ing = meal.get(f"strIngredient{i}")
            measure = meal.get(f"strMeasure{i}")
            if ing and ing.strip():
                measure_str = f"{measure.strip()} " if measure and measure.strip() else ""
                ingredients.append(f"{measure_str}{ing.strip()}")

        results.append(
            f"🍽️ **{name}** ({area} {category})\n"
            f"🖼️ Image: {image_url}\n"
            f"🛒 Ingredients: {', '.join(ingredients[:8])}\n"
            f"📝 Instructions: {instructions}"
        )

    return "\n\n".join(results)


def geocode_address(address: str) -> str:
    """Turn an address into geographic coordinates (latitude, longitude) using Google Geocoding API.

    Args:
        address: The address or city name to geocode.

    Returns:
        A string containing the formatted address and latitude/longitude coordinates.
    """
    api_key = get_maps_api_key()
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY is not set."

    encoded_address = urllib.parse.quote(address.strip())
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_address}&key={api_key}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SmartPantryBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return f"Error connecting to Geocoding API: {e}"

    results = data.get("results")
    if not results:
        status = data.get("status", "UNKNOWN")
        return f"Geocoding failed for '{address}'. Status: {status}"

    first = results[0]
    formatted_address = first.get("formatted_address")
    location = first.get("geometry", {}).get("location", {})
    lat = location.get("lat")
    lng = location.get("lng")

    return (
        f"Address: {formatted_address} | "
        f"Latitude: {lat}, Longitude: {lng}"
    )


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "grocery_store"
) -> str:
    """Find nearby places (like grocery stores or supermarkets) of a given type near coordinates using Places API (New).

    Args:
        latitude: Latitude coordinate.
        longitude: Longitude coordinate.
        place_type: Type of place to search for (default 'grocery_store').

    Returns:
        A list of nearby places with name, address, and coordinates.
    """
    api_key = get_maps_api_key()
    if not api_key:
        return "Error: GOOGLE_MAPS_API_KEY is not set."

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }
    payload = {
        "includedTypes": [place_type],
        "maxResultCount": 5,
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": float(latitude),
                    "longitude": float(longitude),
                },
                "radius": 1000.0,
            }
        },
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return f"Error connecting to Places API (New): {e}"

    places = data.get("places", [])
    if not places:
        return f"No nearby '{place_type}' places found near ({latitude}, {longitude})."

    output = [f"Found {len(places)} nearby '{place_type}' place(s):"]
    for p in places:
        name = p.get("displayName", {}).get("text", "Unknown")
        address = p.get("formattedAddress", "N/A")
        loc = p.get("location", {})
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        output.append(f"- Name: {name}, Address: {address}, Location: ({lat}, {lng})")

    return "\n".join(output)


def generate_recipe_image(
    prompt: str,
    tool_context: ToolContext
) -> str:
    """Generate a photo of a recipe/dish using gemini-3.1-flash-lite-image in global region, save as session artifact, and upload to public GCS bucket.

    Args:
        prompt: Description of the recipe or food item to generate an image for (e.g. 'Fresh avocado toast with poached egg').

    Returns:
        The public HTTPS URL (https://storage.googleapis.com/<bucket>/<object>) of the generated image.
    """
    if not prompt or not prompt.strip():
        return "Error: Please provide a description of the recipe or food item."

    try:
        from google import genai
        from google.genai.types import GenerateContentConfig, Modality
        from google.cloud import storage

        client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=f"Generate a high quality food photo of: {prompt.strip()}",
            config=GenerateContentConfig(
                response_modalities=[Modality.TEXT, Modality.IMAGE]
            )
        )

        image_bytes = None
        if response.candidates:
            for candidate in response.candidates:
                if candidate.content and candidate.content.parts:
                    for part in candidate.content.parts:
                        if part.inline_data and part.inline_data.data:
                            image_bytes = part.inline_data.data
                            break

        if not image_bytes:
            return "Error: Failed to generate image bytes from Gemini model."

        filename = f"recipe_{int(datetime.datetime.now(ZoneInfo('UTC')).timestamp())}.png"

        # (1) Save with tool_context.save_artifact for Playground Artifacts panel
        artifact_part = types.Part.from_bytes(data=image_bytes, mime_type="image/png")
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # (2) Upload image bytes to public Cloud Storage bucket without writing to local file
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(image_bytes, content_type="image/png")

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
        return f"Generated image public URL: {public_url}"

    except Exception as e:
        return f"Error generating or uploading image: {e}"


def generate_recipe_video(
    prompt: str,
    tool_context: ToolContext
) -> str:
    """Generate a short video for a recipe or dish using gemini-omni-flash-preview in global region, save as session artifact, and upload to public GCS bucket.

    Args:
        prompt: Description of the recipe or food video to generate (e.g. 'A short video of a chef plating fresh pasta primavera').

    Returns:
        The public HTTPS URL (https://storage.googleapis.com/<bucket>/<object>) of the generated video.
    """
    if not prompt or not prompt.strip():
        return "Error: Please provide a description of the recipe or food item for video generation."

    try:
        import base64
        from google import genai
        from google.cloud import storage

        client = genai.Client(vertexai=True, project=PROJECT_ID, location="global")
        
        # Call Google's Omni model (gemini-omni-flash-preview) via Interactions API
        interaction = client.interactions.create(
            model="gemini-omni-flash-preview",
            input=f"A short culinary video showing: {prompt.strip()}"
        )

        video_bytes = None
        if hasattr(interaction, "output_video") and interaction.output_video:
            ov = interaction.output_video
            if hasattr(ov, "data") and ov.data:
                if isinstance(ov.data, bytes):
                    video_bytes = ov.data
                elif isinstance(ov.data, str):
                    video_bytes = base64.b64decode(ov.data)

        if not video_bytes and hasattr(interaction, "steps") and interaction.steps:
            for step in interaction.steps:
                if getattr(step, "type", None) == "model_output":
                    for c in getattr(step, "content", []):
                        if getattr(c, "type", None) == "video" or getattr(c, "mime_type", "").startswith("video/"):
                            raw_data = getattr(c, "data", None)
                            if raw_data:
                                if isinstance(raw_data, bytes):
                                    video_bytes = raw_data
                                elif isinstance(raw_data, str):
                                    video_bytes = base64.b64decode(raw_data)

        if not video_bytes:
            return "Error: Failed to extract video bytes from gemini-omni-flash-preview model output."

        filename = f"recipe_video_{int(datetime.datetime.now(ZoneInfo('UTC')).timestamp())}.mp4"

        # (1) Save with tool_context.save_artifact so it shows up in Playground's Artifacts panel
        artifact_part = types.Part.from_bytes(data=video_bytes, mime_type="video/mp4")
        tool_context.save_artifact(filename=filename, artifact=artifact_part)

        # (2) Upload video bytes directly to public Cloud Storage bucket without local file write
        storage_client = storage.Client(project=PROJECT_ID)
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(filename)
        blob.upload_from_string(video_bytes, content_type="video/mp4")

        public_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{filename}"
        return f"Generated video public URL: {public_url}"

    except Exception as e:
        return f"Error generating or uploading video: {e}"


schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are Smart Pantry Recipe Concierge, a helpful culinary AI assistant. "
        "You help users search for local recipes in Firestore using search_recipes, "
        "add new custom recipes using add_recipe, calculate nutritional specs and macros using calculate_recipe_nutrition, "
        "fetch worldwide recipe ideas and images from the web using search_global_recipes, "
        "turn an address into coordinates using geocode_address, find nearby places using find_nearby_places, "
        "generate recipe food images using generate_recipe_image, and generate short recipe videos using generate_recipe_video."
    ),
    workflow_description=(
        "Analyze the request, call tools as needed, and return structured UI or information when appropriate.\n\n"
        "CRITICAL MEMORY & ALLERGY INSTRUCTIONS:\n"
        "1. Active Memory Recall: You remember all user facts, preferences, dietary restrictions, and allergies mentioned in current or previous sessions.\n"
        "2. Strict Allergy Protection: Pay special attention to any allergies (e.g. peanuts, tree nuts, shellfish, dairy/lactose, gluten, soy, eggs) or dietary restrictions mentioned by the user. Always remember them across conversations.\n"
        "3. Safe Recipe Guidance: NEVER suggest, generate, or save a recipe containing ingredients that conflict with the user's remembered allergies without explicitly pointing out the conflict and offering safe substitutes.\n"
        "4. Personalization: Proactively tailor all recipe searches, meal plans, nutrition calculations, food image generations, and video generations to strictly align with the user's allergy profile."
    ),
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
        "not have a public URL, add a short Text line noting the image or video instead. "
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
        model="gemini-2.5-flash",
        project=PROJECT_ID,
        location="us-east1",
    ),
    instruction=instruction,
    tools=[
        search_recipes,
        add_recipe,
        calculate_recipe_nutrition,
        search_global_recipes,
        geocode_address,
        find_nearby_places,
        generate_recipe_image,
        generate_recipe_video,
        PreloadMemoryTool(),
    ],
    after_agent_callback=generate_memories_callback,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
