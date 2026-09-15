#!/usr/bin/env python3
"""
Deterministic data generation and loading for Weaviate backup/restore task.

Generates product and review data with fixed random seed and loads it into
a running Weaviate instance at http://localhost:8080 via the REST batch API.

Prerequisites:
  - Weaviate running on http://localhost:8080
  - Collections 'Products' and 'Reviews' already created
  - Tenants 'store_us', 'store_eu', 'store_asia' already created and active
"""


import random
import json
import uuid
import sys
import time
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

WEAVIATE_URL = "http://localhost:8080"
VECTOR_DIM = 128
SEED = 42

random.seed(SEED)


def generate_vector():
    """Generate a deterministic pseudo-random vector."""
    return [round(random.gauss(0, 1), 6) for _ in range(VECTOR_DIM)]


def make_uuid(namespace, index):
    """Generate a deterministic UUID from namespace and index."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{namespace}-{index}"))


def api_post(path, data):
    """POST JSON data to Weaviate REST API."""
    url = f"{WEAVIATE_URL}{path}"
    body = json.dumps(data).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        print(f"  HTTP {e.code} on POST {path}: {error_body}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"  Connection error on POST {path}: {e}", file=sys.stderr)
        sys.exit(1)


def batch_insert(class_name, tenant, objects):
    """Insert objects via the batch API endpoint."""
    batch_payload = {"objects": []}
    for obj in objects:
        batch_payload["objects"].append({
            "class": class_name,
            "tenant": tenant,
            "properties": obj["properties"],
            "vector": obj["vector"],
            "id": obj["id"],
        })

    result = api_post("/v1/batch/objects", batch_payload)

    errors = []
    for item in result:
        item_result = item.get("result", {})
        if item_result.get("errors"):
            errors.append(item_result["errors"])

    if errors:
        print(f"  Batch errors for {class_name}/{tenant}: {errors}", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# Product data generation
# ---------------------------------------------------------------------------
CATEGORIES = ["electronics", "clothing", "food", "home", "beauty"]
PRODUCT_ADJECTIVES = [
    "Premium", "Ultra", "Professional", "Essential", "Advanced",
    "Classic", "Elite", "Compact", "Rugged", "Precision",
    "Signature", "Heritage",
]
PRODUCT_NOUNS = [
    "Headphones", "Keyboard", "Monitor", "Charger", "Jacket",
    "Boots", "Thermos", "Knife", "Serum", "Speaker",
    "Router", "Backpack",
]

PRODUCT_COUNTS = {"store_us": 12, "store_eu": 10, "store_asia": 8}

print("Loading product data...")
for tenant, count in PRODUCT_COUNTS.items():
    objects = []
    for i in range(count):
        cat = CATEGORIES[i % len(CATEGORIES)]
        adj = PRODUCT_ADJECTIVES[i % len(PRODUCT_ADJECTIVES)]
        noun = PRODUCT_NOUNS[i % len(PRODUCT_NOUNS)]
        region = tenant.split("_")[1].upper()

        obj = {
            "id": make_uuid(f"product-{tenant}", i),
            "properties": {
                "name": f"{adj} {noun} {region}-{i:03d}",
                "description": (
                    f"High-quality {cat} product featuring {adj.lower()} "
                    f"design with durable construction. Model {region}-{i:03d} "
                    f"is engineered for demanding environments and daily use."
                ),
                "category": cat,
                "price": round(random.uniform(5.0, 500.0), 2),
                "in_stock": random.random() > 0.25,
                "sku": f"{region}-P{i:04d}",
            },
            "vector": generate_vector(),
        }
        objects.append(obj)

    if batch_insert("Products", tenant, objects):
        print(f"  Loaded {count} products for {tenant}")
    else:
        print(f"  FAILED to load products for {tenant}", file=sys.stderr)
        sys.exit(1)

# ---------------------------------------------------------------------------
# Review data generation
# ---------------------------------------------------------------------------
REVIEW_TEMPLATES = [
    "Excellent product, exceeded all my expectations in every way",
    "Good value for money with solid construction quality throughout",
    "Average quality overall but has some room for improvement",
    "Outstanding performance during daily use and testing",
    "Decent product with only minor cosmetic flaws noticed",
    "Premium quality materials that are worth every penny spent",
    "Satisfactory purchase that met the basic requirements well",
    "Best in class for this price range compared to competitors",
    "Functional but nothing particularly special about it overall",
    "Impressive build quality and attention to detail throughout",
    "Reliable performance over several months of heavy usage",
    "Slightly below expectations but still acceptable for the price",
    "Superb craftsmanship with excellent packaging and presentation",
    "Works as described with no issues encountered during use",
    "Top-tier product that I would recommend without hesitation",
    "Meets expectations adequately for the advertised use case",
    "Remarkably durable and well-suited for outdoor conditions",
    "Good everyday item that handles normal wear and tear well",
]

AUTHOR_NAMES = [
    "alice_reviews", "bob_smith", "carol_jones", "david_lee",
    "emma_wilson", "frank_chen", "grace_park", "henry_adams",
    "iris_martinez", "james_taylor",
]

REVIEW_COUNTS = {"store_us": 18, "store_eu": 15, "store_asia": 12}

print("Loading review data...")
for tenant, count in REVIEW_COUNTS.items():
    objects = []
    for i in range(count):
        template = REVIEW_TEMPLATES[i % len(REVIEW_TEMPLATES)]
        author = AUTHOR_NAMES[i % len(AUTHOR_NAMES)]
        region = tenant.split("_")[1].upper()

        obj = {
            "id": make_uuid(f"review-{tenant}", i),
            "properties": {
                "content": f"{template}. Review #{i} for the {region} market.",
                "rating": random.randint(1, 5),
                "author": author,
                "verified_purchase": random.random() > 0.3,
            },
            "vector": generate_vector(),
        }
        objects.append(obj)

    if batch_insert("Reviews", tenant, objects):
        print(f"  Loaded {count} reviews for {tenant}")
    else:
        print(f"  FAILED to load reviews for {tenant}", file=sys.stderr)
        sys.exit(1)

print("Data loading complete.")
