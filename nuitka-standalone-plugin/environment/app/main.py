#!/usr/bin/env python3
"""Text processing pipeline with dynamic processor loading."""
import importlib
import os
import pkgutil
import sys


def discover_processors(package_name="backends"):
    """Discover all processor modules dynamically."""
    package = importlib.import_module(package_name)
    processors = {}
    for finder, name, ispkg in pkgutil.iter_modules(package.__path__):
        if name.startswith("text_"):
            mod = importlib.import_module(f"{package_name}.{name}")
            if hasattr(mod, "process"):
                processors[name] = mod.process
    return processors


def load_template(name):
    """Load a template from the data directory."""
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "data", name)
    with open(path, "r") as f:
        return f.read().strip()


def main():
    input_text = "The quick brown fox jumps over the lazy dog"

    header = load_template("header.txt")
    footer = load_template("footer.txt")

    processors = discover_processors()

    print(header)
    for name in sorted(processors.keys()):
        result = processors[name](input_text)
        print(f"  [{name}] {result}")
    print(footer)


if __name__ == "__main__":
    main()
