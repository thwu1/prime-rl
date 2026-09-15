#!/bin/bash
set -e

# Configure git for deterministic commits
git config --global user.name "Test Author"
git config --global user.email "test@example.com"
git config --global init.defaultBranch main

REPO=/app/repo
mkdir -p $REPO
cd $REPO
git init

export GIT_AUTHOR_DATE="2024-01-15T10:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-15T10:00:00+00:00"

# --- Commit 1: Initial project with substantial files ---
mkdir -p src lib

cat > src/engine.py << 'PYEOF'
#!/usr/bin/env python3
"""Processing engine - handles data transformation pipeline."""

import os
import sys
import json
import time
from collections import defaultdict


class ProcessingEngine:
    """Main processing engine for data transformation."""

    VERSION = "1.0.0"
    MAX_BATCH_SIZE = 1000
    DEFAULT_TIMEOUT = 30

    def __init__(self, config=None):
        self.config = config or {}
        self.handlers = {}
        self.metrics = defaultdict(int)
        self._initialized = False

    def initialize(self):
        """Set up the engine with default handlers."""
        if self._initialized:
            return
        self._setup_handlers()
        self._initialized = True

    def _setup_handlers(self):
        """Register default processing handlers."""
        self.handlers['transform'] = self._handle_transform
        self.handlers['validate'] = self._handle_validate
        self.handlers['output'] = self._handle_output

    def _handle_transform(self, data):
        """Transform input data by normalizing keys and values."""
        result = {}
        for key, value in data.items():
            normalized_key = key.strip().upper()
            normalized_value = str(value).strip()
            result[normalized_key] = normalized_value
        self.metrics['transforms'] += 1
        return result

    def _handle_validate(self, data):
        """Validate data structure against required keys."""
        required_keys = self.config.get('required_keys', [])
        for key in required_keys:
            if key not in data:
                raise ValueError(f"Missing required key: {key}")
        self.metrics['validations'] += 1
        return data

    def _handle_output(self, data):
        """Format and output processed data."""
        format_type = self.config.get('output_format', 'json')
        if format_type == 'json':
            result = json.dumps(data, indent=2, sort_keys=True)
        elif format_type == 'csv':
            result = ','.join(f"{k}={v}" for k, v in sorted(data.items()))
        else:
            result = str(data)
        self.metrics['outputs'] += 1
        return result

    def process(self, data, pipeline=None):
        """Run data through the processing pipeline."""
        if not self._initialized:
            self.initialize()
        pipeline = pipeline or ['validate', 'transform', 'output']
        result = data
        for step in pipeline:
            handler = self.handlers.get(step)
            if handler is None:
                raise KeyError(f"Unknown pipeline step: {step}")
            result = handler(result)
        return result

    def get_metrics(self):
        """Return current processing metrics."""
        return dict(self.metrics)

    def reset_metrics(self):
        """Reset all processing metrics to zero."""
        self.metrics.clear()

    def reset(self):
        """Reset engine state completely."""
        self.metrics.clear()
        self.handlers.clear()
        self._initialized = False


def create_engine(config_path=None):
    """Factory function to create a configured engine."""
    config = {}
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    return ProcessingEngine(config)


def main():
    """Entry point for command-line usage."""
    engine = create_engine()
    sample = {"name": "test", "value": "42", "status": "active"}
    result = engine.process(sample)
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYEOF

cat > lib/utils.py << 'PYEOF'
"""Utility functions for data processing."""

import hashlib
import json
import os
from functools import wraps


def memoize(func):
    """Simple memoization decorator."""
    cache = {}
    @wraps(func)
    def wrapper(*args):
        if args not in cache:
            cache[args] = func(*args)
        return cache[args]
    return wrapper


def compute_checksum(data):
    """Compute SHA-256 checksum of data."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def normalize_path(path):
    """Normalize a file path."""
    return os.path.normpath(os.path.expanduser(path))


def read_json(path):
    """Read and parse a JSON file."""
    with open(path) as f:
        return json.load(f)


def write_json(path, data, indent=2):
    """Write data to a JSON file."""
    with open(path, 'w') as f:
        json.dump(data, f, indent=indent)


def chunk_list(lst, size):
    """Split a list into chunks of given size."""
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def flatten(nested):
    """Flatten a nested list structure."""
    result = []
    for item in nested:
        if isinstance(item, (list, tuple)):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result


def deep_merge(base, override):
    """Deep merge two dictionaries."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def format_bytes(size):
    """Format byte size to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
PYEOF

cat > README.md << 'MDEOF'
# Data Processing Framework

A lightweight data transformation pipeline.
MDEOF

git add .
git commit -m "Initial commit with processing engine and utilities"

# --- Commit 2: Add logging and new handler to engine ---
export GIT_AUTHOR_DATE="2024-01-16T10:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-16T10:00:00+00:00"

cat > src/engine.py << 'PYEOF'
#!/usr/bin/env python3
"""Processing engine - handles data transformation pipeline."""

import os
import sys
import json
import time
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class ProcessingEngine:
    """Main processing engine for data transformation."""

    VERSION = "1.1.0"
    MAX_BATCH_SIZE = 1000
    DEFAULT_TIMEOUT = 30

    def __init__(self, config=None):
        self.config = config or {}
        self.handlers = {}
        self.metrics = defaultdict(int)
        self._initialized = False
        self.logger = logging.getLogger(self.__class__.__name__)

    def initialize(self):
        """Set up the engine with default handlers."""
        if self._initialized:
            return
        self._setup_handlers()
        self.logger.info("Engine initialized with %d handlers", len(self.handlers))
        self._initialized = True

    def _setup_handlers(self):
        """Register default processing handlers."""
        self.handlers['transform'] = self._handle_transform
        self.handlers['validate'] = self._handle_validate
        self.handlers['filter'] = self._handle_filter
        self.handlers['output'] = self._handle_output

    def _handle_transform(self, data):
        """Transform input data by normalizing keys and values."""
        result = {}
        for key, value in data.items():
            normalized_key = key.strip().upper()
            normalized_value = str(value).strip()
            result[normalized_key] = normalized_value
        self.metrics['transforms'] += 1
        self.logger.debug("Transformed %d fields", len(result))
        return result

    def _handle_validate(self, data):
        """Validate data structure against required keys."""
        required_keys = self.config.get('required_keys', [])
        for key in required_keys:
            if key not in data:
                self.logger.error("Validation failed: missing key %s", key)
                raise ValueError(f"Missing required key: {key}")
        self.metrics['validations'] += 1
        return data

    def _handle_filter(self, data):
        """Filter data based on configured exclusion rules."""
        exclude_keys = self.config.get('exclude_keys', [])
        result = {k: v for k, v in data.items() if k not in exclude_keys}
        self.metrics['filters'] += 1
        self.logger.debug("Filtered from %d to %d fields", len(data), len(result))
        return result

    def _handle_output(self, data):
        """Format and output processed data."""
        format_type = self.config.get('output_format', 'json')
        if format_type == 'json':
            result = json.dumps(data, indent=2, sort_keys=True)
        elif format_type == 'csv':
            result = ','.join(f"{k}={v}" for k, v in sorted(data.items()))
        else:
            result = str(data)
        self.metrics['outputs'] += 1
        return result

    def process(self, data, pipeline=None):
        """Run data through the processing pipeline."""
        if not self._initialized:
            self.initialize()
        pipeline = pipeline or ['validate', 'transform', 'output']
        result = data
        for step in pipeline:
            handler = self.handlers.get(step)
            if handler is None:
                raise KeyError(f"Unknown pipeline step: {step}")
            self.logger.debug("Executing step: %s", step)
            result = handler(result)
        return result

    def get_metrics(self):
        """Return current processing metrics."""
        return dict(self.metrics)

    def reset_metrics(self):
        """Reset all processing metrics to zero."""
        self.metrics.clear()

    def reset(self):
        """Reset engine state completely."""
        self.metrics.clear()
        self.handlers.clear()
        self._initialized = False


def create_engine(config_path=None):
    """Factory function to create a configured engine."""
    config = {}
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    return ProcessingEngine(config)


def main():
    """Entry point for command-line usage."""
    logging.basicConfig(level=logging.INFO)
    engine = create_engine()
    logger.info("Starting data processing")
    sample = {"name": "test", "value": "42", "status": "active"}
    result = engine.process(sample)
    print(result)
    logger.info("Processing complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYEOF

git add .
git commit -m "Add logging and filter handler to engine"

# --- Commit 3: Add config module, update utils ---
export GIT_AUTHOR_DATE="2024-01-17T10:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-17T10:00:00+00:00"

cat > lib/config.py << 'PYEOF'
"""Configuration management module."""

import json
import os
import copy


DEFAULTS = {
    "debug": False,
    "log_level": "INFO",
    "max_workers": 4,
    "timeout": 30,
    "retry_count": 3,
    "output_format": "json",
}


class Config:
    """Configuration manager with defaults and file loading."""

    def __init__(self, path=None):
        self.data = copy.deepcopy(DEFAULTS)
        self._path = path
        if path and os.path.exists(path):
            self._load_from_file(path)

    def _load_from_file(self, path):
        """Load configuration from JSON file."""
        with open(path) as f:
            user_config = json.load(f)
            self.data.update(user_config)

    def get(self, key, default=None):
        """Get configuration value."""
        return self.data.get(key, default)

    def set(self, key, value):
        """Set configuration value."""
        self.data[key] = value

    def save(self, path=None):
        """Save configuration to JSON file."""
        path = path or self._path
        if path is None:
            raise ValueError("No path specified for saving config")
        with open(path, 'w') as f:
            json.dump(self.data, f, indent=2)

    def as_dict(self):
        """Return configuration as dictionary."""
        return copy.deepcopy(self.data)
PYEOF

# Slightly modify utils.py (add logging, modify deep_merge)
cat > lib/utils.py << 'PYEOF'
"""Utility functions for data processing."""

import hashlib
import json
import os
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def memoize(func):
    """Simple memoization decorator."""
    cache = {}
    @wraps(func)
    def wrapper(*args):
        if args not in cache:
            cache[args] = func(*args)
        return cache[args]
    return wrapper


def compute_checksum(data):
    """Compute SHA-256 checksum of data."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def compute_md5(data):
    """Compute MD5 checksum of data."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.md5(data).hexdigest()


def normalize_path(path):
    """Normalize a file path."""
    return os.path.normpath(os.path.expanduser(path))


def read_json(path):
    """Read and parse a JSON file."""
    logger.debug("Reading JSON from %s", path)
    with open(path) as f:
        return json.load(f)


def write_json(path, data, indent=2):
    """Write data to a JSON file."""
    logger.debug("Writing JSON to %s", path)
    with open(path, 'w') as f:
        json.dump(data, f, indent=indent)


def chunk_list(lst, size):
    """Split a list into chunks of given size."""
    for i in range(0, len(lst), size):
        yield lst[i:i + size]


def flatten(nested):
    """Flatten a nested list structure."""
    result = []
    for item in nested:
        if isinstance(item, (list, tuple)):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result


def deep_merge(base, override, max_depth=10):
    """Deep merge two dictionaries with depth limit."""
    if max_depth <= 0:
        return override
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value, max_depth - 1)
        else:
            result[key] = value
    return result


def format_bytes(size):
    """Format byte size to human readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"
PYEOF

git add .
git commit -m "Add config module and update utilities with logging"

# --- Commit 4: Feature branch ---
git checkout -b feature

export GIT_AUTHOR_DATE="2024-01-18T10:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-18T10:00:00+00:00"

mkdir -p doc

cat > src/feature.py << 'PYEOF'
"""Feature module with additional processing capabilities."""

from lib.utils import compute_checksum, deep_merge
from lib.config import Config


class FeatureProcessor:
    """Processor for feature-specific data transformations."""

    def __init__(self, config=None):
        self.config = config or Config()
        self._cache = {}

    def process(self, data):
        """Process data with feature-specific logic."""
        checksum = compute_checksum(str(data))
        if checksum in self._cache:
            return self._cache[checksum]
        result = self._transform(data)
        self._cache[checksum] = result
        return result

    def _transform(self, data):
        """Apply feature transformation."""
        defaults = {"processed": True, "version": "1.0"}
        return deep_merge(defaults, data)

    def clear_cache(self):
        """Clear the processing cache."""
        self._cache.clear()
PYEOF

cat > doc/guide.md << 'MDEOF'
# Feature Guide

## Overview
The feature module provides additional processing capabilities.

## Usage
```python
from src.feature import FeatureProcessor
proc = FeatureProcessor()
result = proc.process({"key": "value"})
```
MDEOF

git add .
git commit -m "Add feature module and documentation"

# --- Commit 5: Back to main, modify engine and README ---
git checkout main

export GIT_AUTHOR_DATE="2024-01-19T10:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-19T10:00:00+00:00"

cat > src/engine.py << 'PYEOF'
#!/usr/bin/env python3
"""Processing engine - handles data transformation pipeline."""

import os
import sys
import json
import time
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)


class ProcessingError(Exception):
    """Raised when a processing step fails."""
    pass


class ProcessingEngine:
    """Main processing engine for data transformation."""

    VERSION = "2.0.0"
    MAX_BATCH_SIZE = 1000
    DEFAULT_TIMEOUT = 30

    def __init__(self, config=None):
        self.config = config or {}
        self.handlers = {}
        self.metrics = defaultdict(int)
        self._initialized = False
        self.logger = logging.getLogger(self.__class__.__name__)

    def initialize(self):
        """Set up the engine with default handlers."""
        if self._initialized:
            return
        self._setup_handlers()
        self.logger.info("Engine initialized with %d handlers", len(self.handlers))
        self._initialized = True

    def _setup_handlers(self):
        """Register default processing handlers."""
        self.handlers['transform'] = self._handle_transform
        self.handlers['validate'] = self._handle_validate
        self.handlers['filter'] = self._handle_filter
        self.handlers['output'] = self._handle_output

    def _handle_transform(self, data):
        """Transform input data by normalizing keys and values."""
        result = {}
        for key, value in data.items():
            normalized_key = key.strip().upper()
            normalized_value = str(value).strip()
            result[normalized_key] = normalized_value
        self.metrics['transforms'] += 1
        self.logger.debug("Transformed %d fields", len(result))
        return result

    def _handle_validate(self, data):
        """Validate data structure against required keys."""
        required_keys = self.config.get('required_keys', [])
        for key in required_keys:
            if key not in data:
                self.logger.error("Validation failed: missing key %s", key)
                raise ValueError(f"Missing required key: {key}")
        self.metrics['validations'] += 1
        return data

    def _handle_filter(self, data):
        """Filter data based on configured exclusion rules."""
        exclude_keys = self.config.get('exclude_keys', [])
        result = {k: v for k, v in data.items() if k not in exclude_keys}
        self.metrics['filters'] += 1
        self.logger.debug("Filtered from %d to %d fields", len(data), len(result))
        return result

    def _handle_output(self, data):
        """Format and output processed data."""
        format_type = self.config.get('output_format', 'json')
        if format_type == 'json':
            result = json.dumps(data, indent=2, sort_keys=True)
        elif format_type == 'csv':
            result = ','.join(f"{k}={v}" for k, v in sorted(data.items()))
        else:
            result = str(data)
        self.metrics['outputs'] += 1
        return result

    def process(self, data, pipeline=None):
        """Run data through the processing pipeline."""
        if not self._initialized:
            self.initialize()
        pipeline = pipeline or ['validate', 'transform', 'output']
        result = data
        for step in pipeline:
            handler = self.handlers.get(step)
            if handler is None:
                raise KeyError(f"Unknown pipeline step: {step}")
            self.logger.debug("Executing step: %s", step)
            try:
                result = handler(result)
            except Exception as e:
                self.metrics['errors'] += 1
                raise ProcessingError(f"Step '{step}' failed: {e}") from e
        return result

    def batch_process(self, items, pipeline=None):
        """Process multiple items through the pipeline."""
        results = []
        for i, item in enumerate(items):
            self.logger.debug("Processing batch item %d/%d", i + 1, len(items))
            result = self.process(item, pipeline)
            results.append(result)
        self.metrics['batches'] += 1
        return results

    def get_metrics(self):
        """Return current processing metrics."""
        return dict(self.metrics)

    def reset_metrics(self):
        """Reset all processing metrics to zero."""
        self.metrics.clear()

    def reset(self):
        """Reset engine state completely."""
        self.metrics.clear()
        self.handlers.clear()
        self._initialized = False


def create_engine(config_path=None):
    """Factory function to create a configured engine."""
    config = {}
    if config_path and os.path.exists(config_path):
        with open(config_path) as f:
            config = json.load(f)
    return ProcessingEngine(config)


def main():
    """Entry point for command-line usage."""
    logging.basicConfig(level=logging.INFO)
    engine = create_engine()
    logger.info("Starting data processing")
    sample = {"name": "test", "value": "42", "status": "active"}
    result = engine.process(sample)
    print(result)
    logger.info("Processing complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PYEOF

cat > README.md << 'MDEOF'
# Data Processing Framework

A lightweight data transformation pipeline.

## Modules

- `src/engine.py` - Main processing engine
- `lib/utils.py` - Utility functions
- `lib/config.py` - Configuration management

## Usage

```python
from src.engine import create_engine

engine = create_engine("config.json")
result = engine.process({"key": "value"})
```
MDEOF

git add .
git commit -m "Add error handling and batch processing to engine"

# --- Commit 6: Merge feature branch ---
export GIT_AUTHOR_DATE="2024-01-20T10:00:00+00:00"
export GIT_COMMITTER_DATE="2024-01-20T10:00:00+00:00"

git merge feature --no-edit -m "Merge feature branch into main"

# --- Pack all objects ---
git gc --aggressive --prune=now

# Verify the pack exists and has delta objects
echo "=== Pack file contents ==="
PACK_DIR="$REPO/.git/objects/pack"
IDX_FILE=$(ls "$PACK_DIR"/*.idx 2>/dev/null | head -1)

if [ -z "$IDX_FILE" ]; then
    echo "ERROR: No pack index file found!"
    exit 1
fi

TOTAL=$(git verify-pack -v "$IDX_FILE" 2>/dev/null | grep -c '^[0-9a-f]\{40\}')
DELTAS=$(git verify-pack -v "$IDX_FILE" 2>/dev/null | awk 'NF>=7 && /^[0-9a-f]{40}/' | wc -l)

echo "Total objects: $TOTAL"
echo "Delta objects: $DELTAS"

if [ "$DELTAS" -eq 0 ]; then
    echo "WARNING: No delta objects created. Forcing repack with delta compression..."
    git repack -a -d --depth=50 --window=250
    IDX_FILE=$(ls "$PACK_DIR"/*.idx 2>/dev/null | head -1)
    DELTAS=$(git verify-pack -v "$IDX_FILE" 2>/dev/null | awk 'NF>=7 && /^[0-9a-f]{40}/' | wc -l)
    echo "Delta objects after repack: $DELTAS"
fi

echo "Repository setup complete."

# --- Remove the pack index to create the challenge ---
echo "Removing pack index file..."
rm -f "$PACK_DIR"/*.idx

# --- Zero out the pack file's trailing SHA-1 checksum ---
echo "Corrupting pack checksum..."
PACK_FILE=$(ls "$PACK_DIR"/*.pack | head -1)
PACK_SIZE=$(stat -c%s "$PACK_FILE")
dd if=/dev/zero of="$PACK_FILE" bs=1 count=20 seek=$((PACK_SIZE - 20)) conv=notrunc 2>/dev/null
echo "Pack index removed and checksum zeroed. Repository requires dual repair."
