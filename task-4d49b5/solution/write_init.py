#!/usr/bin/env python3
"""Write the typesim __init__.py module."""

content = '''"""TypeSim — structural type similarity scoring engine."""

from .parser import parse_type, TypeNode
from .similarity import get_type_similarity

__all__ = ["parse_type", "TypeNode", "get_type_similarity"]
'''

with open("/app/typesim/__init__.py", "w") as f:
    f.write(content)
