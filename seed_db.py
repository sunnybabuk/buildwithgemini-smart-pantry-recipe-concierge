#!/usr/bin/env python3
"""Seed script for populating the Firestore 'recipes' collection."""

from google.cloud import firestore

# CRITICAL: Hardcode the project ID as a string, DO NOT read from GOOGLE_CLOUD_PROJECT or google.auth.default()
PROJECT_ID = "qwiklabs-gcp-02-f418aae87c3d"

SEEDED_RECIPES = [
    {
        "id": "recipe-001",
        "name": "Garlic Butter Salmon with Asparagus",
        "prep_time_mins": 20,
        "cuisine": "Mediterranean",
        "main_ingredients": ["salmon", "asparagus", "butter", "garlic", "lemon"],
        "dietary_tags": ["keto", "gluten-free", "low-carb"],
        "instructions": "1. Season salmon with salt and pepper. 2. Sauté asparagus in garlic butter until tender. 3. Pan-sear salmon 4 mins per side.",
        "calories": 450,
    },
    {
        "id": "recipe-002",
        "name": "Quinoa Veggie Power Bowl",
        "prep_time_mins": 15,
        "cuisine": "Healthy / American",
        "main_ingredients": ["quinoa", "chickpeas", "avocado", "spinach", "tahini"],
        "dietary_tags": ["vegan", "vegetarian", "gluten-free"],
        "instructions": "1. Cook quinoa according to package instructions. 2. Top with roasted chickpeas, sliced avocado, and fresh spinach. 3. Drizzle with tahini dressing.",
        "calories": 380,
    },
    {
        "id": "recipe-003",
        "name": "Classic Tomato Basil Pasta",
        "prep_time_mins": 25,
        "cuisine": "Italian",
        "main_ingredients": ["pasta", "tomatoes", "basil", "olive oil", "garlic", "parmesan"],
        "dietary_tags": ["vegetarian"],
        "instructions": "1. Boil pasta until al dente. 2. Simmer crushed tomatoes, garlic, and olive oil for 15 mins. 3. Toss pasta with sauce and fresh basil.",
        "calories": 520,
    },
    {
        "id": "recipe-004",
        "name": "Thai Basil Chicken Stir-Fry",
        "prep_time_mins": 15,
        "cuisine": "Thai",
        "main_ingredients": ["chicken", "thai basil", "bell pepper", "soy sauce", "chili", "garlic"],
        "dietary_tags": ["high-protein", "dairy-free"],
        "instructions": "1. Stir-fry minced chicken with garlic and chili. 2. Add sliced bell peppers and soy sauce. 3. Fold in fresh Thai basil leaves right before serving.",
        "calories": 410,
    },
    {
        "id": "recipe-005",
        "name": "Creamy Mushroom Risotto",
        "prep_time_mins": 35,
        "cuisine": "Italian",
        "main_ingredients": ["arborio rice", "mushrooms", "vegetable broth", "shallots", "parmesan", "thyme"],
        "dietary_tags": ["vegetarian", "gluten-free"],
        "instructions": "1. Sauté mushrooms and shallots in butter. 2. Toast arborio rice and gradually add warm broth while stirring. 3. Stir in parmesan and thyme.",
        "calories": 480,
    }
]


def seed_firestore():
    print(f"Connecting to Firestore for project: {PROJECT_ID}...")
    db = firestore.Client(project=PROJECT_ID)
    collection_ref = db.collection("recipes")

    for recipe in SEEDED_RECIPES:
        doc_id = recipe["id"]
        doc_ref = collection_ref.document(doc_id)
        doc_ref.set(recipe)
        print(f"  ✓ Seeded recipe: {recipe['name']} (ID: {doc_id})")

    print(f"Successfully seeded {len(SEEDED_RECIPES)} recipes into Firestore!")


if __name__ == "__main__":
    seed_firestore()
