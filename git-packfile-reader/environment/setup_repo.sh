#!/bin/bash
set -e

export GIT_AUTHOR_NAME="Test User"
export GIT_AUTHOR_EMAIL="test@example.com"
export GIT_COMMITTER_NAME="Test User"
export GIT_COMMITTER_EMAIL="test@example.com"

mkdir -p /app/repo
cd /app/repo
git init

# --- Commit 1: Initial project files ---
export GIT_AUTHOR_DATE="2024-01-01T12:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-01T12:00:00+00:00"

mkdir -p src lib docs

cat > README.md << 'EOF'
# Sample Project

This is a sample project used for testing Git internals.
It contains various source files organized in a typical project structure.
EOF

cat > src/main.py << 'EOF'
#!/usr/bin/env python3
"""Main entry point for the application."""

def main():
    print("Hello, World!")
    return 0

if __name__ == "__main__":
    exit(main())
EOF

cat > src/utils.py << 'EOF'
"""Utility functions for the application."""

def format_name(first, last):
    return f"{first} {last}"

def validate_email(email):
    return "@" in email and "." in email
EOF

cat > lib/math_ops.py << 'EOF'
"""Mathematical operations library."""

def add(a, b):
    return a + b

def subtract(a, b):
    return a - b

def multiply(a, b):
    return a * b
EOF

cat > lib/__init__.py << 'EOF'
"""Library package initialization."""
from .math_ops import add, subtract, multiply
EOF

cat > docs/guide.md << 'EOF'
# User Guide

## Getting Started

1. Install dependencies
2. Run the main script
3. Check the output

## Configuration

See config.py for configuration options.
EOF

git add .
git commit -m "Initial project setup with source files and documentation"

# --- Commit 2: Add features and modify files (creates similar blobs for delta compression) ---
export GIT_AUTHOR_DATE="2024-01-02T12:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-02T12:00:00+00:00"

cat > README.md << 'EOF'
# Sample Project

This is a sample project used for testing Git internals.
It contains various source files organized in a typical project structure.

## Features

- Math operations library
- Utility functions
- Comprehensive documentation

## Installation

```
pip install -r requirements.txt
```
EOF

cat > src/main.py << 'EOF'
#!/usr/bin/env python3
"""Main entry point for the application."""

import sys
from lib.math_ops import add, multiply

def main():
    print("Hello, World!")
    print(f"2 + 3 = {add(2, 3)}")
    print(f"4 * 5 = {multiply(4, 5)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
EOF

cat > src/config.py << 'EOF'
"""Application configuration."""

CONFIG = {
    "app_name": "Sample Project",
    "version": "0.2.0",
    "debug": False,
    "log_level": "INFO",
}
EOF

cat > lib/math_ops.py << 'EOF'
"""Mathematical operations library."""

def add(a, b):
    """Add two numbers."""
    return a + b

def subtract(a, b):
    """Subtract b from a."""
    return a - b

def multiply(a, b):
    """Multiply two numbers."""
    return a * b

def divide(a, b):
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
EOF

git add .
git commit -m "Add features, configuration, and improve math library"

# --- Commit 3: More modifications to create more deltas ---
export GIT_AUTHOR_DATE="2024-01-03T12:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-03T12:00:00+00:00"

cat > src/utils.py << 'EOF'
"""Utility functions for the application."""

import re

def format_name(first, last):
    """Format a full name from first and last name."""
    return f"{first} {last}"

def validate_email(email):
    """Validate an email address format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))

def truncate(text, max_length=100):
    """Truncate text to max_length characters."""
    if len(text) <= max_length:
        return text
    return text[:max_length-3] + "..."
EOF

cat > lib/string_ops.py << 'EOF'
"""String operations library."""

def reverse(s):
    """Reverse a string."""
    return s[::-1]

def capitalize_words(s):
    """Capitalize the first letter of each word."""
    return ' '.join(word.capitalize() for word in s.split())

def count_vowels(s):
    """Count the number of vowels in a string."""
    return sum(1 for c in s.lower() if c in 'aeiou')
EOF

cat > lib/__init__.py << 'EOF'
"""Library package initialization."""
from .math_ops import add, subtract, multiply, divide
from .string_ops import reverse, capitalize_words, count_vowels
EOF

cat > docs/api.md << 'EOF'
# API Reference

## Math Operations

- `add(a, b)` - Add two numbers
- `subtract(a, b)` - Subtract b from a
- `multiply(a, b)` - Multiply two numbers
- `divide(a, b)` - Divide a by b

## String Operations

- `reverse(s)` - Reverse a string
- `capitalize_words(s)` - Capitalize first letter of each word
- `count_vowels(s)` - Count vowels in a string

## Utilities

- `format_name(first, last)` - Format a full name
- `validate_email(email)` - Validate email format
- `truncate(text, max_length)` - Truncate text
EOF

git add .
git commit -m "Add string operations, API docs, and improve utilities"

# --- Create an annotated tag ---
git tag -a v0.1.0 -m "First release" HEAD~2

# --- Commit 4: Final modifications ---
export GIT_AUTHOR_DATE="2024-01-04T12:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-04T12:00:00+00:00"

cat > src/config.py << 'EOF'
"""Application configuration."""

import os

CONFIG = {
    "app_name": "Sample Project",
    "version": "0.3.0",
    "debug": os.environ.get("DEBUG", "false").lower() == "true",
    "log_level": os.environ.get("LOG_LEVEL", "INFO"),
    "max_retries": 3,
    "timeout": 30,
}

def get_config(key, default=None):
    """Get a configuration value."""
    return CONFIG.get(key, default)
EOF

cat > src/main.py << 'EOF'
#!/usr/bin/env python3
"""Main entry point for the application."""

import sys
from lib.math_ops import add, multiply, divide
from lib.string_ops import reverse, capitalize_words
from src.config import get_config

def main():
    app_name = get_config("app_name", "Unknown")
    version = get_config("version", "0.0.0")
    print(f"{app_name} v{version}")
    print(f"2 + 3 = {add(2, 3)}")
    print(f"4 * 5 = {multiply(4, 5)}")
    print(f"10 / 3 = {divide(10, 3):.2f}")
    print(f"Reversed 'hello': {reverse('hello')}")
    print(f"Capitalized: {capitalize_words('hello world')}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
EOF

git add .
git commit -m "Final updates: improve config and main entry point"

# --- Pack all objects and remove loose objects ---
git gc --aggressive --prune=now

# Remove any remaining loose objects to force packfile-only reading
find .git/objects -type f ! -path '*.pack' ! -path '*.idx' ! -path '*info*' -delete 2>/dev/null || true
find .git/objects -type d -empty -delete 2>/dev/null || true
mkdir -p .git/objects/info .git/objects/pack

# Verify packfiles exist
echo "Pack files created:"
ls -la .git/objects/pack/
echo "Total objects in pack:"
git rev-list --objects --all | wc -l
echo "Setup complete."
