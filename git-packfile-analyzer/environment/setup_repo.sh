#!/bin/bash
set -e

cd /app
mkdir -p repo
cd repo

git init -b master
git config user.email "test@test.com"
git config user.name "Test User"

# Commit 1: Initial files
mkdir -p src/utils docs

cat > src/main.py << 'EOF'
#!/usr/bin/env python3
"""Main entry point for the sample application."""

def hello():
    """Print a hello message."""
    print("Hello, World!")

def main():
    hello()

if __name__ == "__main__":
    main()
EOF

cat > src/utils/math_ops.py << 'EOF'
"""Mathematical operations module."""

def add(a, b):
    """Add two numbers."""
    return a + b

def subtract(a, b):
    """Subtract b from a."""
    return a - b
EOF

cat > src/utils/__init__.py << 'EOF'
# Utils package
EOF

cat > README.md << 'EOF'
# Sample Project

A sample project for testing git packfile internals.

## Overview

This project demonstrates basic Python project structure.
EOF

cat > docs/architecture.md << 'EOF'
# Architecture

## Module Structure

- src/main.py: Application entry point
- src/utils/: Utility modules
EOF

git add -A
git commit -m "Initial commit: project skeleton"

# Commit 2: Extend functionality (creates similar blobs for delta compression)
cat > src/main.py << 'EOF'
#!/usr/bin/env python3
"""Main entry point for the sample application."""

from utils.math_ops import add, subtract

def hello():
    """Print a hello message."""
    print("Hello, World!")
    print("Welcome to the sample project!")

def goodbye():
    """Print a goodbye message."""
    print("Goodbye, World!")

def calculate():
    """Demonstrate math operations."""
    result = add(10, 20)
    print(f"10 + 20 = {result}")
    result = subtract(20, 5)
    print(f"20 - 5 = {result}")

def main():
    hello()
    calculate()
    goodbye()

if __name__ == "__main__":
    main()
EOF

cat > src/utils/math_ops.py << 'EOF'
"""Mathematical operations module."""

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

def power(a, b):
    """Raise a to the power of b."""
    return a ** b
EOF

cat > src/test_math.py << 'EOF'
"""Tests for math_ops module."""
import unittest
from utils.math_ops import add, subtract, multiply, divide, power

class TestMathOps(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)
        self.assertEqual(add(-1, 1), 0)

    def test_subtract(self):
        self.assertEqual(subtract(5, 3), 2)
        self.assertEqual(subtract(0, 5), -5)

    def test_multiply(self):
        self.assertEqual(multiply(3, 4), 12)
        self.assertEqual(multiply(0, 100), 0)

    def test_divide(self):
        self.assertEqual(divide(10, 2), 5)
        with self.assertRaises(ValueError):
            divide(1, 0)

    def test_power(self):
        self.assertEqual(power(2, 10), 1024)
        self.assertEqual(power(5, 0), 1)

if __name__ == "__main__":
    unittest.main()
EOF

git add -A
git commit -m "Add math functions, tests, and calculator"

# Commit 3: Add configuration
cat > src/config.py << 'EOF'
"""Application configuration."""
import os

class Config:
    DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
    APP_NAME = "SampleApp"
    VERSION = "0.1.0"
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    MAX_RETRIES = 3
    TIMEOUT_SECONDS = 30
EOF

cat > README.md << 'EOF'
# Sample Project

A sample project for testing git packfile internals.

## Overview

This project demonstrates basic Python project structure.

## Installation

Clone the repository and run the main module:

    python src/main.py

## Configuration

Set environment variables:
- DEBUG: Enable debug mode (true/false)
- LOG_LEVEL: Set logging level (DEBUG, INFO, WARNING, ERROR)

## Testing

Run the test suite:

    python -m pytest src/test_math.py
EOF

git add -A
git commit -m "Add configuration module and update README"

# Create feature branch for string utilities
git checkout -b feature/string-utils

cat > src/utils/string_ops.py << 'EOF'
"""String utility operations."""

def reverse(s):
    """Reverse a string."""
    return s[::-1]

def capitalize_words(s):
    """Capitalize each word in a string."""
    return ' '.join(word.capitalize() for word in s.split())

def count_vowels(s):
    """Count vowels in a string."""
    return sum(1 for c in s.lower() if c in 'aeiou')

def is_palindrome(s):
    """Check if a string is a palindrome."""
    cleaned = ''.join(c.lower() for c in s if c.isalnum())
    return cleaned == cleaned[::-1]

def truncate(s, max_length, suffix="..."):
    """Truncate a string to max_length, adding suffix if truncated."""
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix
EOF

cat > src/test_string.py << 'EOF'
"""Tests for string_ops module."""
import unittest
from utils.string_ops import reverse, capitalize_words, count_vowels, is_palindrome, truncate

class TestStringOps(unittest.TestCase):
    def test_reverse(self):
        self.assertEqual(reverse("hello"), "olleh")
        self.assertEqual(reverse(""), "")

    def test_capitalize_words(self):
        self.assertEqual(capitalize_words("hello world"), "Hello World")

    def test_count_vowels(self):
        self.assertEqual(count_vowels("hello"), 2)
        self.assertEqual(count_vowels("xyz"), 0)

    def test_is_palindrome(self):
        self.assertTrue(is_palindrome("racecar"))
        self.assertFalse(is_palindrome("hello"))
        self.assertTrue(is_palindrome("A man a plan a canal Panama"))

    def test_truncate(self):
        self.assertEqual(truncate("hello", 10), "hello")
        self.assertEqual(truncate("hello world", 8), "hello...")

if __name__ == "__main__":
    unittest.main()
EOF

git add -A
git commit -m "Add string utility functions"

git checkout master

# Commit on master (diverge from feature branch)
cat > src/main.py << 'EOF'
#!/usr/bin/env python3
"""Main entry point for the sample application."""

from utils.math_ops import add, subtract, multiply
from config import Config

def hello():
    """Print a hello message."""
    print(f"Hello from {Config.APP_NAME} v{Config.VERSION}!")
    print("Welcome to the sample project!")

def goodbye():
    """Print a goodbye message."""
    print("Goodbye, World!")

def calculate():
    """Demonstrate math operations."""
    operations = [
        ("10 + 20", add(10, 20)),
        ("20 - 5", subtract(20, 5)),
        ("6 * 7", multiply(6, 7)),
    ]
    for desc, result in operations:
        print(f"  {desc} = {result}")

def main():
    if Config.DEBUG:
        print("[DEBUG MODE ENABLED]")
    hello()
    print("\nCalculations:")
    calculate()
    goodbye()

if __name__ == "__main__":
    main()
EOF

git add -A
git commit -m "Integrate config into main module"

# Merge feature branch with --no-ff to create a merge commit
git merge feature/string-utils --no-ff -m "Merge feature/string-utils into master"

# Pack everything aggressively to ensure delta compression
git gc --aggressive --prune=now

echo "Repository setup complete. Applying corruptions..."

# ===== APPLY CORRUPTIONS =====
# All git commands MUST happen before this point.

# Corruption 1: Change pack version from 2 to 3 AND zero out trailing checksum
python3 -c "
import struct, glob
pack_files = glob.glob('/app/repo/.git/objects/pack/*.pack')
for pf in pack_files:
    with open(pf, 'rb') as f:
        data = f.read()
    # Change version (bytes 4-7) from 2 to 3, zero checksum (last 20 bytes)
    corrupted = data[:4] + struct.pack('>I', 3) + data[8:-20] + b'\x00' * 20
    with open(pf, 'wb') as f:
        f.write(corrupted)
"

# Corruption 2: Delete pack index file
rm -f /app/repo/.git/objects/pack/*.idx

# Corruption 3: Corrupt feature/string-utils ref in packed-refs (change last hex char)
python3 -c "
with open('/app/repo/.git/packed-refs', 'r') as f:
    lines = f.readlines()
with open('/app/repo/.git/packed-refs', 'w') as f:
    for line in lines:
        if 'refs/heads/feature/string-utils' in line:
            parts = line.strip().split(' ', 1)
            sha = parts[0]
            new_char = '0' if sha[-1] != '0' else '1'
            new_sha = sha[:-1] + new_char
            f.write(new_sha + ' ' + parts[1] + '\n')
        else:
            f.write(line)
"

# Corruption 4: Plant spurious shallow file (makes git think repo is shallow)
python3 -c "
with open('/app/repo/.git/packed-refs', 'r') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and 'refs/heads/master' in line:
            sha = line.split()[0]
            with open('/app/repo/.git/shallow', 'w') as sf:
                sf.write(sha + '\n')
            break
"

# Corruption 5: Point HEAD to non-existent branch 'main' instead of 'master'
echo "ref: refs/heads/main" > /app/repo/.git/HEAD

# Remove reflogs to prevent trivial recovery of correct ref SHAs
rm -rf /app/repo/.git/logs

echo "Corruptions applied."
