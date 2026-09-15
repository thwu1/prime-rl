#!/usr/bin/env python3
"""Generate a deterministic source code corpus for the suffix array search task."""
import os
import json

CORPUS_DIR = "/app/corpus"
os.makedirs(CORPUS_DIR, exist_ok=True)

# --- File 1: algorithms.py ---
algorithms_py = '''\
"""Algorithm implementations for data processing pipeline."""

import hashlib
from collections import defaultdict


def compute_rolling_hash(data, window_size=16):
    """Compute rolling hash using Rabin-Karp method."""
    MOD = (1 << 61) - 1
    BASE = 131
    result = []
    if len(data) < window_size:
        return result
    current_hash = 0
    base_power = pow(BASE, window_size - 1, MOD)
    for i in range(window_size):
        current_hash = (current_hash * BASE + ord(data[i])) % MOD
    result.append((0, current_hash))
    for i in range(1, len(data) - window_size + 1):
        current_hash = (current_hash - ord(data[i-1]) * base_power) % MOD
        current_hash = (current_hash * BASE + ord(data[i + window_size - 1])) % MOD
        result.append((i, current_hash))
    return result


def process_batch_records(records, batch_size=256):
    """Process records in fixed-size batches for memory efficiency."""
    processed = []
    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]
        # TODO: add validation for each record in the batch
        filtered = [r for r in batch if r.get("valid", False)]
        processed.extend(filtered)
    return processed


def handle_error_recovery(error_state, max_retries=3):
    """Handle error recovery with exponential backoff."""
    import time
    for attempt in range(max_retries):
        delay = 2 ** attempt
        # WARNING: this blocks the calling thread
        time.sleep(delay)
        if error_state.try_recover():
            return True
    return False


def transform_stream_data(stream, transformations):
    """Apply a chain of transformations to a data stream."""
    for transform in transformations:
        stream = map(transform, stream)
    return list(stream)


def validate_batch_integrity(batch_data, checksums):
    """Validate data integrity against known checksums."""
    for item, expected in zip(batch_data, checksums):
        actual = hashlib.md5(str(item).encode()).hexdigest()
        if actual != expected:
            raise ValueError(f"Integrity check failed: {actual} != {expected}")
    return True


# FIXME: this class is incomplete and needs error handling
class DataAggregator:
    """Aggregate data from multiple sources."""

    def __init__(self, sources):
        self.sources = sources
        self.cache = defaultdict(list)

    def aggregate(self):
        """Aggregate all sources into unified dataset."""
        for source in self.sources:
            for record in source.read():
                key = record.get("category", "unknown")
                self.cache[key].append(record)
        return dict(self.cache)

    def process_aggregated_results(self, results):
        """Post-process aggregated results."""
        # todo: implement proper deduplication strategy
        return {k: list(set(str(v) for v in vals)) for k, vals in results.items()}
'''

# --- File 2: networking.c ---
networking_c = '''\
/* Network server implementation with connection pooling. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <pthread.h>

#define MAX_CONNECTIONS 1024
#define BUFFER_SIZE 4096
#define DEFAULT_PORT 8080

/* WARNING: not thread-safe without external locking */
static int connection_pool[MAX_CONNECTIONS];
static int pool_count = 0;

typedef struct {
    int sockfd;
    struct sockaddr_in addr;
    char buffer[BUFFER_SIZE];
    int authenticated;
} client_connection_t;

int handle_client_connection(int sockfd, client_connection_t *conn) {
    int bytes_read;
    memset(conn->buffer, 0, BUFFER_SIZE);
    bytes_read = read(sockfd, conn->buffer, BUFFER_SIZE - 1);
    if (bytes_read <= 0) {
        return -1;
    }
    /* TODO: implement proper HTTP parsing here */
    return process_http_request(conn);
}

int process_http_request(client_connection_t *conn) {
    char *method = strtok(conn->buffer, " ");
    char *path = strtok(NULL, " ");

    if (method == NULL || path == NULL) {
        return handle_malformed_request(conn);
    }

    if (strcmp(method, "GET") == 0) {
        return handle_get_request(conn, path);
    } else if (strcmp(method, "POST") == 0) {
        return handle_post_request(conn, path);
    }

    /* FIXME: handle other HTTP methods like PUT and DELETE */
    return -1;
}

int handle_get_request(client_connection_t *conn, const char *path) {
    char response[BUFFER_SIZE];
    snprintf(response, BUFFER_SIZE,
             "HTTP/1.1 200 OK\\r\\nContent-Type: text/plain\\r\\n\\r\\nHello from %s",
             path);
    return write(conn->sockfd, response, strlen(response));
}

int handle_post_request(client_connection_t *conn, const char *path) {
    /* TODO: implement POST handling with body parsing */
    return handle_get_request(conn, path);
}

int handle_malformed_request(client_connection_t *conn) {
    const char *response = "HTTP/1.1 400 Bad Request\\r\\n\\r\\n";
    return write(conn->sockfd, response, strlen(response));
}

void *connection_handler_thread(void *arg) {
    client_connection_t *conn = (client_connection_t *)arg;
    handle_client_connection(conn->sockfd, conn);
    close(conn->sockfd);
    free(conn);
    return NULL;
}

int validate_connection_params(int sockfd, struct sockaddr_in *addr) {
    if (sockfd < 0) return -1;
    if (addr->sin_port == 0) return -1;
    /* WARNING: does not validate address range */
    return 0;
}

int start_server(int port) {
    int server_fd;
    struct sockaddr_in address;

    server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        perror("socket failed");
        return -1;
    }

    address.sin_family = AF_INET;
    address.sin_addr.s_addr = INADDR_ANY;
    address.sin_port = htons(port);

    if (bind(server_fd, (struct sockaddr *)&address, sizeof(address)) < 0) {
        perror("bind failed");
        return -1;
    }

    /* FIXME: make backlog configurable via environment variable */
    if (listen(server_fd, 10) < 0) {
        perror("listen failed");
        return -1;
    }

    return server_fd;
}
'''

# --- File 3: config.ini ---
config_ini = '''\
[database]
host = localhost
port = 5432
name = production_db
user = app_service
; TODO: rotate credentials quarterly per security policy
password = change_me_in_production

[logging]
level = WARNING
format = %(asctime)s - %(name)s - %(levelname)s - %(message)s
; todo: add structured logging support for ELK stack
file = /var/log/app/server.log

[cache]
backend = redis
host = cache.internal
port = 6379
ttl_seconds = 3600
; FIXME: cache invalidation strategy needed for multi-region

[performance]
max_workers = 8
batch_size = 256
process_timeout = 30
; WARNING: increasing max_workers beyond CPU count degrades performance
'''

# --- File 4: data_pipeline.py ---
data_pipeline_py = '''\
"""Data pipeline for ETL operations with batch processing support."""

import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    batch_size: int = 256
    max_retries: int = 3
    timeout_seconds: int = 30
    enable_deduplication: bool = True


class DataPipeline:
    """Main data pipeline orchestrator."""

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.stages = []
        self.error_handlers = {}

    def process_batch_items(self, items: List[Dict]) -> List[Dict]:
        """Process a batch of items through all pipeline stages."""
        results = items
        for stage in self.stages:
            results = stage.execute(results)
            if not results:
                logger.warning("Stage %s produced empty results", stage.name)
                break
        return results

    def handle_pipeline_error(self, error: Exception, context: Dict) -> bool:
        """Handle errors during pipeline execution."""
        error_type = type(error).__name__
        handler = self.error_handlers.get(error_type)
        if handler:
            return handler(error, context)
        # FIXME: add default error handling strategy
        logger.error("Unhandled pipeline error: %s", error)
        return False

    def validate_pipeline_config(self) -> bool:
        """Validate pipeline configuration before execution."""
        if self.config.batch_size <= 0:
            raise ValueError("batch_size must be positive")
        if self.config.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        # TODO: validate stage compatibility and ordering
        return True

    def compute_pipeline_metrics(self) -> Dict[str, Any]:
        """Compute performance metrics for the pipeline."""
        metrics = {
            "total_stages": len(self.stages),
            "batch_size": self.config.batch_size,
            "error_handler_count": len(self.error_handlers),
        }
        return metrics


class TransformStage:
    """A transformation stage in the data pipeline."""

    def __init__(self, name: str, transform_fn):
        self.name = name
        self.transform_fn = transform_fn
        self.processed_count = 0

    def execute(self, items: List[Dict]) -> List[Dict]:
        """Execute transformation on batch items."""
        results = []
        for item in items:
            try:
                transformed = self.transform_fn(item)
                if transformed is not None:
                    results.append(transformed)
                    self.processed_count += 1
            except Exception as e:
                # WARNING: silently dropping failed items
                logger.warning("Transform failed for item: %s", e)
        return results


class FilterStage:
    """A filtering stage that removes items not matching criteria."""

    def __init__(self, name: str, predicate):
        self.name = name
        self.predicate = predicate

    def execute(self, items: List[Dict]) -> List[Dict]:
        """Filter items based on predicate."""
        return [item for item in items if self.predicate(item)]


def process_streaming_data(stream, pipeline: DataPipeline) -> List[Dict]:
    """Process a data stream through the pipeline in batches."""
    all_results = []
    batch = []
    for item in stream:
        batch.append(item)
        if len(batch) >= pipeline.config.batch_size:
            results = pipeline.process_batch_items(batch)
            all_results.extend(results)
            batch = []
    if batch:
        results = pipeline.process_batch_items(batch)
        all_results.extend(results)
    return all_results


def validate_stream_schema(stream, schema: Dict) -> bool:
    """Validate that stream items conform to expected schema."""
    for item in stream:
        for field, field_type in schema.items():
            if field not in item:
                return False
            if not isinstance(item[field], field_type):
                return False
    return True
'''

# --- File 5: utils.py ---
utils_py = '''\
"""Utility functions for system operations and file handling."""

import os
import sys
import shutil
import tempfile
from pathlib import Path


def compute_file_checksum(filepath, algorithm="sha256"):
    """Compute checksum of a file using specified algorithm."""
    import hashlib
    h = hashlib.new(algorithm)
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def process_directory_tree(root_path, pattern="*"):
    """Recursively process all matching files in directory tree."""
    results = []
    root = Path(root_path)
    for filepath in root.rglob(pattern):
        if filepath.is_file():
            results.append({
                "path": str(filepath),
                "size": filepath.stat().st_size,
                "modified": filepath.stat().st_mtime,
            })
    return results


def handle_file_operation_error(operation, filepath, error):
    """Handle errors during file operations with logging."""
    error_map = {
        "read": "Failed to read file",
        "write": "Failed to write file",
        "delete": "Failed to delete file",
    }
    msg = error_map.get(operation, "Unknown file operation failed")
    # WARNING: error details may contain sensitive path information
    print(f"ERROR: {msg}: {filepath}: {error}", file=sys.stderr)
    return False


def validate_path_security(filepath):
    """Validate that a filepath does not contain path traversal attacks."""
    normalized = os.path.normpath(filepath)
    if ".." in normalized.split(os.sep):
        raise ValueError(f"Path traversal detected: {filepath}")
    # TODO: add symlink resolution check for additional safety
    return normalized


def transform_file_encoding(input_path, output_path, from_enc="utf-8", to_enc="utf-8"):
    """Transform file encoding from one format to another."""
    with open(input_path, "r", encoding=from_enc) as fin:
        content = fin.read()
    with open(output_path, "w", encoding=to_enc) as fout:
        fout.write(content)
    return True


# FIXME: this doesn\'t handle race conditions properly
def safe_atomic_write(filepath, content, mode="w"):
    """Write content atomically using temporary file and rename."""
    dirpath = os.path.dirname(filepath) or "."
    with tempfile.NamedTemporaryFile(mode=mode, dir=dirpath, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    os.rename(tmp_path, filepath)
    return True


class FileWatcher:
    """Watch files for changes using polling."""

    def __init__(self, paths, interval=1.0):
        self.paths = paths
        self.interval = interval
        self._checksums = {}

    def compute_current_state(self):
        """Compute current state of all watched files."""
        state = {}
        for path in self.paths:
            if os.path.exists(path):
                state[path] = compute_file_checksum(path)
        return state

    def detect_changes(self):
        """Detect which files have changed since last check."""
        current = self.compute_current_state()
        changed = []
        for path, checksum in current.items():
            if self._checksums.get(path) != checksum:
                changed.append(path)
        self._checksums = current
        return changed
'''

# --- Write static files ---
files = {
    "algorithms.py": algorithms_py,
    "networking.c": networking_c,
    "config.ini": config_ini,
    "data_pipeline.py": data_pipeline_py,
    "utils.py": utils_py,
}

for name, content in files.items():
    path = os.path.join(CORPUS_DIR, name)
    with open(path, "w") as f:
        f.write(content)

# --- Generate large file for performance testing ---
large_lines = []
words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
ops = ["compute", "transform", "validate", "process", "handle", "aggregate"]
targets = ["result", "value", "output", "metric", "score", "index"]

for i in range(20000):
    seed = i * 17 + 42
    w1 = words[seed % len(words)]
    w2 = words[(seed * 3 + 7) % len(words)]
    op = ops[(seed * 5 + 13) % len(ops)]
    tgt = targets[(seed * 11 + 3) % len(targets)]
    large_lines.append(f"entry_{i:06d}: {w1}_{w2}_{tgt} = {op}_{w1}_data({seed})")
    if i % 500 == 0:
        large_lines.append(f"# process_batch_checkpoint at entry {i}")
    if i % 2500 == 0:
        large_lines.append(f"# TODO: optimize batch processing after entry {i}")
    if i % 3000 == 0:
        large_lines.append(f"# WARNING: performance degradation observed at entry {i}")

large_content = "\n".join(large_lines)
with open(os.path.join(CORPUS_DIR, "large_dataset.txt"), "w") as f:
    f.write(large_content)

# --- Write manifest for reference ---
manifest = {}
for name in list(files.keys()) + ["large_dataset.txt"]:
    fpath = os.path.join(CORPUS_DIR, name)
    with open(fpath) as f:
        content = f.read()
    manifest[name] = {
        "lines": content.count("\n") + (1 if not content.endswith("\n") else 0),
        "bytes": len(content.encode("utf-8")),
    }

with open("/app/corpus_manifest.json", "w") as f:
    json.dump(manifest, f, indent=2)

total_bytes = sum(v["bytes"] for v in manifest.values())
total_lines = sum(v["lines"] for v in manifest.values())
print(f"Corpus generated: {len(manifest)} files, {total_lines} lines, {total_bytes} bytes")
for name, info in sorted(manifest.items()):
    print(f"  {name}: {info['lines']} lines, {info['bytes']} bytes")
