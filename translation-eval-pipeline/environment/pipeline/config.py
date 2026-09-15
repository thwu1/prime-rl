"""Configuration for the translation benchmark evaluation pipeline.

Loads settings from /app/pipeline_config.json.
"""

import json

with open("/app/pipeline_config.json") as _f:
    _config = json.load(_f)

DYNAMIC_LANGUAGES = set(_config["language_types"]["dynamic"])
STATIC_LANGUAGES = set(_config["language_types"]["static"])
FRAMEWORK_PARSER_MAP = _config["framework_parsers"]

DATA_DIR = "/data/benchmark"
RESULTS_FILE = "/app/results.json"
