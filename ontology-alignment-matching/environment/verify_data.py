#!/usr/bin/env python3
"""Verify generated OWL ontology data is correct."""
import re
import sys

for name, path, min_classes, min_props in [
    ("source", "/app/data/source.owl", 140, 10),
    ("target", "/app/data/target.owl", 150, 10),
]:
    with open(path) as f:
        content = f.read()
    n_classes = len(re.findall(r'<owl:Class\s+rdf:about=', content))
    n_props = len(re.findall(r'<owl:ObjectProperty\s+rdf:about=', content))
    print(f"Verify {name}: {n_classes} classes, {n_props} properties")
    if n_classes < min_classes or n_props < min_props:
        print(f"ERROR: {name} has too few elements ({n_classes} classes, {n_props} props)")
        sys.exit(1)

# Verify example alignment exists
import os
assert os.path.isfile("/app/data/example_alignment.rdf"), "Missing example alignment"
assert os.path.isfile("/app/data/README.md"), "Missing README"
assert os.path.isdir("/app/output"), "Missing output directory"
print("All verification checks passed")
