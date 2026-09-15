#!/usr/bin/env python3
"""
Setup script for the git object store reconstruction task.
Creates a git repo with specific history, exports all objects to a
JSON-based archive format, then destroys the original repo.

Runs during Docker build and is removed afterward.
"""
import json
import os
import re
import shutil
import subprocess
import sys

TEMP_REPO = "/tmp/build_repo"
ARCHIVE = "/app/archive"
REPO = "/app/repo"


def run(cmd, cwd=None, check=True):
    r = subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)
    if check and r.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}", file=sys.stderr)
        print(r.stderr, file=sys.stderr)
        sys.exit(1)
    return r


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def set_date(n):
    """Set fixed git dates for deterministic commits."""
    ts = 1705000000 + n * 86400
    os.environ["GIT_AUTHOR_DATE"] = f"{ts} +0000"
    os.environ["GIT_COMMITTER_DATE"] = f"{ts} +0000"


# ---- File contents for each version ----

README_V1 = """\
# DataFlow Pipeline
A data processing pipeline framework.
Version 0.1
"""

PARSER_V1 = '''\
"""Data parser module."""


class DataParser:
    def __init__(self, schema):
        self.schema = schema
        self._validators = []

    def parse(self, raw_input):
        tokens = self._tokenize(raw_input)
        return self._build_ast(tokens)

    def _tokenize(self, data):
        return [line.strip() for line in data.splitlines() if line.strip()]

    def _build_ast(self, tokens):
        return {"type": "document", "children": tokens}

    def register_validator(self, validator):
        self._validators.append(validator)
'''

TRANSFORM_V1 = '''\
"""Data transformation module."""


class DataTransformer:
    def __init__(self):
        self._transforms = []

    def add_transform(self, fn):
        self._transforms.append(fn)
        return self

    def execute(self, data):
        result = data
        for fn in self._transforms:
            result = fn(result)
        return result
'''

HELPERS_V1 = '''\
"""Utility functions."""
import hashlib
import json


def compute_checksum(data):
    return hashlib.sha256(data.encode()).hexdigest()


def load_config(path):
    with open(path) as f:
        return json.load(f)


def deep_merge(base, override):
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result
'''

CONFIG_V1 = """\
name: dataflow
version: "0.1.0"
pipeline:
  workers: 4
  batch_size: 100
  timeout_ms: 5000
logging:
  level: INFO
  format: "%(asctime)s %(levelname)s %(message)s"
"""

VALIDATOR_V1 = '''\
"""Validation module."""


class SchemaValidator:
    def __init__(self, schema_def):
        self.schema = schema_def
        self._rules = {}

    def add_rule(self, field, rule_fn):
        self._rules[field] = rule_fn

    def validate(self, record):
        errors = []
        for field, rule in self._rules.items():
            if field not in record:
                errors.append(f"Missing required field: {field}")
            elif not rule(record[field]):
                errors.append(f"Validation failed for: {field}")
        return len(errors) == 0, errors
'''

PARSER_V2 = '''\
"""Data parser module with validation support."""


class DataParser:
    def __init__(self, schema):
        self.schema = schema
        self._validators = []

    def parse(self, raw_input):
        tokens = self._tokenize(raw_input)
        ast = self._build_ast(tokens)
        if self._validators:
            self._run_validators(ast)
        return ast

    def _tokenize(self, data):
        return [line.strip() for line in data.splitlines() if line.strip()]

    def _build_ast(self, tokens):
        return {"type": "document", "children": tokens}

    def register_validator(self, validator):
        self._validators.append(validator)

    def _run_validators(self, ast):
        for v in self._validators:
            v.validate(ast)
'''

CONSUMER_V1 = '''\
"""Stream consumer module."""


class StreamConsumer:
    def __init__(self, source, batch_size=10):
        self.source = source
        self.batch_size = batch_size
        self._offset = 0

    def consume(self):
        batch = []
        while len(batch) < self.batch_size:
            record = self.source.read(self._offset)
            if record is None:
                break
            batch.append(record)
            self._offset += 1
        return batch

    def commit_offset(self):
        self.source.acknowledge(self._offset)
'''

PRODUCER_V1 = '''\
"""Stream producer module."""


class StreamProducer:
    def __init__(self, sink, serializer=None):
        self.sink = sink
        self.serializer = serializer or str

    def produce(self, records):
        serialized = [self.serializer(r) for r in records]
        return self.sink.write_batch(serialized)

    def flush(self):
        self.sink.flush()
'''

STREAMING_CONFIG = """\
streaming:
  buffer_size: 1024
  max_batch_wait_ms: 500
  consumer_group: "dataflow-default"
  auto_commit: true
"""

BUFFER_V1 = '''\
"""Stream buffer for batching and backpressure."""
from collections import deque


class StreamBuffer:
    def __init__(self, capacity=1024):
        self.capacity = capacity
        self._buffer = deque(maxlen=capacity)
        self._overflow_count = 0

    def push(self, item):
        if len(self._buffer) >= self.capacity:
            self._overflow_count += 1
            return False
        self._buffer.append(item)
        return True

    def pop_batch(self, size):
        batch = []
        while self._buffer and len(batch) < size:
            batch.append(self._buffer.popleft())
        return batch

    @property
    def utilization(self):
        return len(self._buffer) / self.capacity if self.capacity else 0
'''

CONSUMER_V2 = '''\
"""Stream consumer module with buffering."""
from src.streaming.buffer import StreamBuffer


class StreamConsumer:
    def __init__(self, source, batch_size=10, buffer_capacity=1024):
        self.source = source
        self.batch_size = batch_size
        self._offset = 0
        self._buffer = StreamBuffer(buffer_capacity)

    def consume(self):
        self._fill_buffer()
        return self._buffer.pop_batch(self.batch_size)

    def _fill_buffer(self):
        while self._buffer.utilization < 0.8:
            record = self.source.read(self._offset)
            if record is None:
                break
            self._buffer.push(record)
            self._offset += 1

    def commit_offset(self):
        self.source.acknowledge(self._offset)
'''

PARSER_V3 = '''\
"""Data parser module — refactored for pipeline integration."""


class DataParser:
    def __init__(self, schema):
        self.schema = schema
        self._validators = []
        self._hooks = {"pre_parse": [], "post_parse": []}

    def parse(self, raw_input):
        self._fire_hooks("pre_parse", raw_input)
        tokens = self._tokenize(raw_input)
        ast = self._build_ast(tokens)
        if self._validators:
            self._run_validators(ast)
        self._fire_hooks("post_parse", ast)
        return ast

    def _tokenize(self, data):
        return [line.strip() for line in data.splitlines() if line.strip()]

    def _build_ast(self, tokens):
        return {"type": "document", "children": tokens, "meta": {"count": len(tokens)}}

    def register_validator(self, validator):
        self._validators.append(validator)

    def add_hook(self, event, fn):
        if event in self._hooks:
            self._hooks[event].append(fn)

    def _run_validators(self, ast):
        for v in self._validators:
            v.validate(ast)

    def _fire_hooks(self, event, data):
        for hook in self._hooks.get(event, []):
            hook(data)
'''

TRANSFORM_V2 = '''\
"""Data transformation module — enhanced."""


class DataTransformer:
    def __init__(self):
        self._transforms = []
        self._error_handler = None

    def add_transform(self, fn, name=None):
        self._transforms.append({"fn": fn, "name": name or fn.__name__})
        return self

    def set_error_handler(self, handler):
        self._error_handler = handler

    def execute(self, data):
        result = data
        for t in self._transforms:
            try:
                result = t["fn"](result)
            except Exception as e:
                if self._error_handler:
                    result = self._error_handler(e, result, t["name"])
                else:
                    raise
        return result
'''

PIPELINE_V1 = '''\
"""Pipeline orchestrator."""
from src.core.parser import DataParser
from src.core.transform import DataTransformer
from src.core.validator import SchemaValidator


class Pipeline:
    def __init__(self, config):
        self.config = config
        self.parser = DataParser(config.get("schema"))
        self.transformer = DataTransformer()
        self.validator = SchemaValidator(config.get("schema"))

    def run(self, input_data):
        parsed = self.parser.parse(input_data)
        valid, errors = self.validator.validate(parsed)
        if not valid:
            raise ValueError(f"Validation errors: {errors}")
        return self.transformer.execute(parsed)
'''

CHANGELOG_V1 = """\
# Changelog

## v1.0.0

### Added
- Pipeline orchestrator for unified data processing
- Validation layer with schema support
- Pre/post parse hooks in DataParser
- Error handling in DataTransformer

### Changed
- Refactored parser for pipeline integration
- Enhanced transformer with named transforms
"""

CONFIG_V2 = """\
name: dataflow
version: "1.0.0"
pipeline:
  workers: 4
  batch_size: 100
  timeout_ms: 5000
  retry_count: 3
logging:
  level: INFO
  format: "%(asctime)s %(levelname)s %(message)s"
  output: stdout
"""


def create_repo():
    """Create the git repository with full commit history on two branches."""
    os.makedirs(TEMP_REPO, exist_ok=True)

    run(["git", "init", "-b", "main"], cwd=TEMP_REPO)
    run(["git", "config", "user.name", "Alice Developer"], cwd=TEMP_REPO)
    run(["git", "config", "user.email", "alice@example.com"], cwd=TEMP_REPO)
    run(["git", "config", "gc.auto", "0"], cwd=TEMP_REPO)
    run(["git", "config", "commit.gpgSign", "false"], cwd=TEMP_REPO)

    # ---- Commit 1: Initial project structure ----
    set_date(1)
    write_file(f"{TEMP_REPO}/README.md", README_V1)
    write_file(f"{TEMP_REPO}/src/core/parser.py", PARSER_V1)
    write_file(f"{TEMP_REPO}/src/core/transform.py", TRANSFORM_V1)
    write_file(f"{TEMP_REPO}/src/utils/helpers.py", HELPERS_V1)
    write_file(f"{TEMP_REPO}/config/pipeline.yaml", CONFIG_V1)
    run(["git", "add", "."], cwd=TEMP_REPO)
    run(["git", "commit", "-m", "Initial project structure"], cwd=TEMP_REPO)

    # ---- Commit 2: Add validation layer ----
    set_date(2)
    write_file(f"{TEMP_REPO}/src/core/validator.py", VALIDATOR_V1)
    write_file(f"{TEMP_REPO}/src/core/parser.py", PARSER_V2)
    run(["git", "add", "."], cwd=TEMP_REPO)
    run(["git", "commit", "-m", "Add validation layer"], cwd=TEMP_REPO)

    # ---- Branch feature/streaming from commit 2 ----
    run(["git", "checkout", "-b", "feature/streaming"], cwd=TEMP_REPO)

    # Commit 3 (branch): Add streaming support
    set_date(3)
    write_file(f"{TEMP_REPO}/src/streaming/consumer.py", CONSUMER_V1)
    write_file(f"{TEMP_REPO}/src/streaming/producer.py", PRODUCER_V1)
    write_file(f"{TEMP_REPO}/config/streaming.yaml", STREAMING_CONFIG)
    run(["git", "add", "."], cwd=TEMP_REPO)
    run(["git", "commit", "-m", "Add streaming support"], cwd=TEMP_REPO)

    # Commit 4 (branch): Stream buffering
    set_date(4)
    write_file(f"{TEMP_REPO}/src/streaming/buffer.py", BUFFER_V1)
    write_file(f"{TEMP_REPO}/src/streaming/consumer.py", CONSUMER_V2)
    run(["git", "add", "."], cwd=TEMP_REPO)
    run(["git", "commit", "-m", "Add stream buffering with backpressure"], cwd=TEMP_REPO)

    # Save feature/streaming HEAD hash
    feature_hash = run(["git", "rev-parse", "HEAD"], cwd=TEMP_REPO).stdout.strip()

    # ---- Back to main ----
    run(["git", "checkout", "main"], cwd=TEMP_REPO)

    # Commit 3 (main): Refactor pipeline architecture
    set_date(5)
    write_file(f"{TEMP_REPO}/src/core/parser.py", PARSER_V3)
    write_file(f"{TEMP_REPO}/src/core/transform.py", TRANSFORM_V2)
    write_file(f"{TEMP_REPO}/src/pipeline.py", PIPELINE_V1)
    run(["git", "add", "."], cwd=TEMP_REPO)
    run(["git", "commit", "-m", "Refactor pipeline architecture"], cwd=TEMP_REPO)

    # Commit 4 (main): Release v1.0
    set_date(6)
    write_file(f"{TEMP_REPO}/CHANGELOG.md", CHANGELOG_V1)
    write_file(f"{TEMP_REPO}/config/pipeline.yaml", CONFIG_V2)
    run(["git", "add", "."], cwd=TEMP_REPO)
    run(["git", "commit", "-m", "Release v1.0"], cwd=TEMP_REPO)

    # Create annotated tag
    set_date(7)
    run(["git", "tag", "-a", "v1.0", "-m", "Version 1.0 release"], cwd=TEMP_REPO)

    # Save main HEAD hash
    main_hash = run(["git", "rev-parse", "HEAD"], cwd=TEMP_REPO).stdout.strip()

    return main_hash, feature_hash


def export_archive(main_hash, feature_hash):
    """Export all git objects to JSON archive format."""
    os.makedirs(f"{ARCHIVE}/objects", exist_ok=True)

    # Collect all reachable object SHAs
    all_objects = set()
    result = run(["git", "rev-list", "--all", "--objects"], cwd=TEMP_REPO)
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        if parts:
            all_objects.add(parts[0])

    # Add annotated tag objects (not listed by rev-list --objects)
    tag_result = run(["git", "tag", "-l"], cwd=TEMP_REPO)
    for tag in tag_result.stdout.strip().split("\n"):
        tag = tag.strip()
        if tag:
            sha = run(["git", "rev-parse", tag], cwd=TEMP_REPO).stdout.strip()
            obj_type = run(["git", "cat-file", "-t", sha], cwd=TEMP_REPO).stdout.strip()
            if obj_type == "tag":
                all_objects.add(sha)

    types_map = {}

    for sha in sorted(all_objects):
        obj_type = run(["git", "cat-file", "-t", sha], cwd=TEMP_REPO).stdout.strip()
        types_map[sha] = obj_type

        if obj_type == "blob":
            content = run(["git", "cat-file", "blob", sha], cwd=TEMP_REPO).stdout
            obj_json = {"content": content}

        elif obj_type == "tree":
            output = run(["git", "cat-file", "-p", sha], cwd=TEMP_REPO).stdout
            entries = []
            for line in output.strip().split("\n"):
                if not line.strip():
                    continue
                # Format: <mode> <type> <sha1>\t<name>
                parts = line.split("\t", 1)
                meta = parts[0].split()
                entries.append({
                    "mode": meta[0],
                    "type": meta[1],
                    "sha1": meta[2],
                    "name": parts[1]
                })
            obj_json = {"entries": entries}

        elif obj_type == "commit":
            raw = run(["git", "cat-file", "commit", sha], cwd=TEMP_REPO).stdout
            header, _, message = raw.partition("\n\n")
            obj = {"parents": []}
            for line in header.split("\n"):
                if line.startswith("tree "):
                    obj["tree"] = line[5:]
                elif line.startswith("parent "):
                    obj["parents"].append(line[7:])
                elif line.startswith("author "):
                    m = re.match(
                        r"(.+) <(.+?)> (\d+) ([+-]\d{4})", line[7:]
                    )
                    obj["author_name"] = m.group(1)
                    obj["author_email"] = m.group(2)
                    obj["author_timestamp"] = int(m.group(3))
                    obj["author_tz"] = m.group(4)
                elif line.startswith("committer "):
                    m = re.match(
                        r"(.+) <(.+?)> (\d+) ([+-]\d{4})", line[10:]
                    )
                    obj["committer_name"] = m.group(1)
                    obj["committer_email"] = m.group(2)
                    obj["committer_timestamp"] = int(m.group(3))
                    obj["committer_tz"] = m.group(4)
            obj["message"] = message.rstrip("\n")
            obj_json = obj

        elif obj_type == "tag":
            raw = run(["git", "cat-file", "tag", sha], cwd=TEMP_REPO).stdout
            header, _, message = raw.partition("\n\n")
            obj = {}
            for line in header.split("\n"):
                if line.startswith("object "):
                    obj["object"] = line[7:]
                elif line.startswith("type "):
                    obj["target_type"] = line[5:]
                elif line.startswith("tag "):
                    obj["tag_name"] = line[4:]
                elif line.startswith("tagger "):
                    m = re.match(
                        r"(.+) <(.+?)> (\d+) ([+-]\d{4})", line[7:]
                    )
                    obj["tagger_name"] = m.group(1)
                    obj["tagger_email"] = m.group(2)
                    obj["tagger_timestamp"] = int(m.group(3))
                    obj["tagger_tz"] = m.group(4)
            obj["message"] = message.rstrip("\n")
            obj_json = obj

        else:
            continue

        with open(f"{ARCHIVE}/objects/{sha}.json", "w") as f:
            json.dump(obj_json, f, indent=2, ensure_ascii=False)

    # Write types map
    with open(f"{ARCHIVE}/types.json", "w") as f:
        json.dump(types_map, f, indent=2, sort_keys=True)

    # Write refs — feature/streaming ref deliberately omitted
    tag_sha = run(["git", "rev-parse", "v1.0"], cwd=TEMP_REPO).stdout.strip()

    refs = {
        "HEAD": "ref: refs/heads/main",
        "branches": {
            "main": main_hash,
        },
        "tags": {
            "v1.0": tag_sha,
        },
        "_export_warning": (
            "The feature/streaming branch ref was lost during export. "
            "Reconstruct it from the commit graph."
        ),
    }

    with open(f"{ARCHIVE}/refs.json", "w") as f:
        json.dump(refs, f, indent=2)

    # Write metadata for verification
    metadata = {
        "repository": "DataFlow Pipeline",
        "branches": {
            "main": {
                "commit_count": 4,
                "head_message": "Release v1.0",
            },
            "feature/streaming": {
                "commit_count": 4,
                "head_message": "Add stream buffering with backpressure",
            },
        },
        "tags": {
            "v1.0": {
                "annotated": True,
                "target": "main HEAD",
                "message": "Version 1.0 release",
            },
        },
    }

    with open(f"{ARCHIVE}/metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)


def main():
    main_hash, feature_hash = create_repo()
    export_archive(main_hash, feature_hash)
    shutil.rmtree(TEMP_REPO)
    os.makedirs(REPO, exist_ok=True)
    print("Archive created successfully.")


if __name__ == "__main__":
    main()
