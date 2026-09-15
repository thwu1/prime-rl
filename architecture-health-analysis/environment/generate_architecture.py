#!/usr/bin/env python3
"""Generate architecture data for the BigSpender e-commerce system analysis task.

This creates a realistic 30-component architecture with intentional dependency
cycles, layering violations, and architectural principle violations inspired by
iSAQB CPSA-A examination system types (information system / web system).
"""
import json
import os

def generate():
    components = [
        # Infrastructure API layer (stable, abstract)
        {"name": "persistence-api", "abstract_types": 12, "concrete_types": 2},
        {"name": "messaging-api", "abstract_types": 8, "concrete_types": 1},
        {"name": "security-api", "abstract_types": 10, "concrete_types": 2},
        {"name": "caching-api", "abstract_types": 6, "concrete_types": 1},
        {"name": "logging-api", "abstract_types": 5, "concrete_types": 1},
        # Domain layer (moderately stable, mixed abstraction)
        {"name": "user-domain", "abstract_types": 4, "concrete_types": 8},
        {"name": "product-domain", "abstract_types": 5, "concrete_types": 10},
        {"name": "order-domain", "abstract_types": 6, "concrete_types": 12},
        {"name": "payment-domain", "abstract_types": 4, "concrete_types": 9},
        {"name": "inventory-domain", "abstract_types": 3, "concrete_types": 7},
        {"name": "catalog-domain", "abstract_types": 3, "concrete_types": 8},
        {"name": "pricing-domain", "abstract_types": 2, "concrete_types": 6},
        {"name": "shipping-domain", "abstract_types": 3, "concrete_types": 7},
        {"name": "notification-domain", "abstract_types": 2, "concrete_types": 5},
        # Application service layer (moderately unstable)
        {"name": "auth-service", "abstract_types": 1, "concrete_types": 8},
        {"name": "product-service", "abstract_types": 2, "concrete_types": 11},
        {"name": "order-service", "abstract_types": 2, "concrete_types": 14},
        {"name": "payment-service", "abstract_types": 1, "concrete_types": 10},
        {"name": "cart-service", "abstract_types": 1, "concrete_types": 9},
        {"name": "search-service", "abstract_types": 1, "concrete_types": 7},
        {"name": "recommendation-service", "abstract_types": 0, "concrete_types": 8},
        {"name": "analytics-service", "abstract_types": 1, "concrete_types": 6},
        {"name": "reporting-service", "abstract_types": 0, "concrete_types": 9},
        # Infrastructure adapter layer (unstable, concrete)
        {"name": "postgres-adapter", "abstract_types": 0, "concrete_types": 6},
        {"name": "redis-adapter", "abstract_types": 0, "concrete_types": 4},
        {"name": "rabbitmq-adapter", "abstract_types": 0, "concrete_types": 5},
        {"name": "elasticsearch-adapter", "abstract_types": 0, "concrete_types": 4},
        {"name": "stripe-adapter", "abstract_types": 0, "concrete_types": 5},
        # Presentation layer (most unstable)
        {"name": "web-frontend", "abstract_types": 0, "concrete_types": 15},
        {"name": "api-gateway", "abstract_types": 1, "concrete_types": 12},
    ]

    dependencies = [
        # Presentation -> Application Services
        ["web-frontend", "api-gateway"],
        ["web-frontend", "auth-service"],
        ["api-gateway", "auth-service"],
        ["api-gateway", "product-service"],
        ["api-gateway", "order-service"],
        ["api-gateway", "payment-service"],
        ["api-gateway", "cart-service"],
        ["api-gateway", "search-service"],
        # Application Services -> Domain
        ["auth-service", "user-domain"],
        ["auth-service", "security-api"],
        ["product-service", "product-domain"],
        ["product-service", "catalog-domain"],
        ["product-service", "pricing-domain"],
        ["order-service", "order-domain"],
        ["order-service", "payment-domain"],
        ["order-service", "inventory-domain"],
        ["order-service", "shipping-domain"],
        ["payment-service", "payment-domain"],
        ["cart-service", "product-domain"],
        ["cart-service", "pricing-domain"],
        ["cart-service", "order-service"],
        ["search-service", "product-domain"],
        ["search-service", "catalog-domain"],
        ["recommendation-service", "product-domain"],
        ["recommendation-service", "analytics-service"],
        ["analytics-service", "order-domain"],
        ["analytics-service", "user-domain"],
        ["analytics-service", "recommendation-service"],
        ["reporting-service", "order-domain"],
        ["reporting-service", "analytics-service"],
        ["reporting-service", "product-domain"],
        # Domain -> Infrastructure API
        ["user-domain", "persistence-api"],
        ["user-domain", "security-api"],
        ["product-domain", "persistence-api"],
        ["product-domain", "caching-api"],
        ["order-domain", "persistence-api"],
        ["order-domain", "messaging-api"],
        ["order-domain", "payment-domain"],
        ["payment-domain", "persistence-api"],
        ["payment-domain", "security-api"],
        ["payment-domain", "messaging-api"],
        ["payment-domain", "order-domain"],
        ["inventory-domain", "persistence-api"],
        ["inventory-domain", "messaging-api"],
        ["catalog-domain", "persistence-api"],
        ["catalog-domain", "caching-api"],
        ["catalog-domain", "pricing-domain"],
        ["pricing-domain", "persistence-api"],
        ["pricing-domain", "caching-api"],
        ["pricing-domain", "catalog-domain"],
        ["shipping-domain", "persistence-api"],
        ["shipping-domain", "messaging-api"],
        ["notification-domain", "messaging-api"],
        ["notification-domain", "logging-api"],
        ["notification-domain", "recommendation-service"],
        # Adapters -> Infrastructure API
        ["postgres-adapter", "persistence-api"],
        ["redis-adapter", "caching-api"],
        ["rabbitmq-adapter", "messaging-api"],
        ["elasticsearch-adapter", "persistence-api"],
        ["stripe-adapter", "payment-domain"],
        # Intentional architectural violations
        ["security-api", "web-frontend"],
    ]

    refactoring_operations = [
        {"id": "refactor-01", "description": "Extract interfaces in product-domain",
         "target": "product-domain", "add_abstract_types": 5, "cost": 15},
        {"id": "refactor-02", "description": "Introduce service interfaces in auth-service",
         "target": "auth-service", "add_abstract_types": 4, "cost": 12},
        {"id": "refactor-03", "description": "Abstract payment-service boundaries",
         "target": "payment-service", "add_abstract_types": 5, "cost": 14},
        {"id": "refactor-04", "description": "Define recommendation contracts",
         "target": "recommendation-service", "add_abstract_types": 4, "cost": 10},
        {"id": "refactor-05", "description": "Introduce view-model abstractions in web-frontend",
         "target": "web-frontend", "add_abstract_types": 6, "cost": 18},
        {"id": "refactor-06", "description": "Extract order processing interfaces",
         "target": "order-service", "add_abstract_types": 3, "cost": 10},
        {"id": "refactor-07", "description": "Define analytics event contracts",
         "target": "analytics-service", "add_abstract_types": 2, "cost": 8},
        {"id": "refactor-08", "description": "Abstract search query models",
         "target": "search-service", "add_abstract_types": 3, "cost": 9},
        {"id": "refactor-09", "description": "Extract cart domain interfaces",
         "target": "cart-service", "add_abstract_types": 2, "cost": 7},
        {"id": "refactor-10", "description": "Define catalog query contracts",
         "target": "catalog-domain", "add_abstract_types": 2, "cost": 8},
        {"id": "refactor-11", "description": "Abstract pricing calculation rules",
         "target": "pricing-domain", "add_abstract_types": 3, "cost": 9},
        {"id": "refactor-12", "description": "Extract order aggregate interfaces",
         "target": "order-domain", "add_abstract_types": 4, "cost": 11},
    ]

    budget = 55

    os.makedirs("/app/architecture", exist_ok=True)

    with open("/app/architecture/components.json", "w") as f:
        json.dump({"components": components}, f, indent=2)

    with open("/app/architecture/dependencies.json", "w") as f:
        json.dump({"dependencies": dependencies}, f, indent=2)

    with open("/app/architecture/refactoring_operations.json", "w") as f:
        json.dump({"operations": refactoring_operations, "budget": budget}, f, indent=2)

if __name__ == "__main__":
    generate()
