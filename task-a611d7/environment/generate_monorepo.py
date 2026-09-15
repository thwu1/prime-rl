#!/usr/bin/env python3
"""Generate the monorepo package structure for the dependency health audit task."""
import os

BASE = "/app/monorepo"

TOOLS_DEFS_BZL = """\
# Macro for service-level Python library targets.
#
# service_deps: bare package names (without // prefix)
# internal_deps: full Bazel labels (with // prefix)
#
# Both are merged into the underlying py_library's deps list.
def py_service(name, srcs, service_deps=[], internal_deps=[], **kwargs):
    py_library(
        name = name,
        srcs = srcs,
        deps = ["//" + d for d in service_deps] + internal_deps,
        **kwargs
    )
"""

# All packages: build_type is "standard" (py_library) or "macro" (py_service)
# For standard: "build_deps" lists the deps in the BUILD file
# For macro: "service_deps" and "internal_deps" list the macro args
# "code" is the module.py source code
PACKAGES = {
    "core": {
        "build_type": "standard",
        "build_deps": [],
        "code": """\
# Core types and constants for the monorepo
class Result:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def is_ok(self):
        return self.error is None


class Config:
    _defaults = {"timeout": 30, "retries": 3, "debug": False}

    def __init__(self, **kwargs):
        self._data = {**self._defaults, **kwargs}

    def get(self, key, default=None):
        return self._data.get(key, default)


VERSION = "2.1.0"
"""
    },
    "utils": {
        "build_type": "standard",
        "build_deps": ["core"],
        "code": """\
from monorepo.core.module import Result, VERSION


def safe_divide(a, b):
    if b == 0:
        return Result(error="Division by zero")
    return Result(value=a / b)


def version_tuple():
    return tuple(int(x) for x in VERSION.split("."))


def flatten(nested_list):
    result = []
    for item in nested_list:
        if isinstance(item, list):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result
"""
    },
    "config": {
        "build_type": "standard",
        "build_deps": ["core"],
        "code": """\
from monorepo.core.module import Config

import json
import os


class AppConfig(Config):
    def __init__(self, config_path=None):
        super().__init__()
        if config_path and os.path.exists(config_path):
            with open(config_path) as f:
                self._data.update(json.load(f))

    def validate(self):
        required = ["timeout", "retries"]
        return all(k in self._data for k in required)
"""
    },
    "logging": {
        "build_type": "standard",
        "build_deps": ["core"],
        "code": """\
from monorepo.core.module import Config

import sys
from datetime import datetime


class Logger:
    LEVELS = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}

    def __init__(self, name, level="INFO"):
        self.name = name
        self.level = self.LEVELS.get(level, 1)

    def log(self, level, message):
        if self.LEVELS.get(level, 0) >= self.level:
            ts = datetime.now().isoformat()
            print(f"[{ts}] [{level}] [{self.name}] {message}", file=sys.stderr)

    def info(self, msg):
        self.log("INFO", msg)

    def error(self, msg):
        self.log("ERROR", msg)

    def debug(self, msg):
        self.log("DEBUG", msg)
"""
    },
    "crypto": {
        "build_type": "standard",
        "build_deps": ["core"],
        "code": """\
from monorepo.core.module import Result

import hashlib
import hmac


def hash_password(password, salt="default_salt"):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt.encode(), 100000
    ).hex()


def verify_hmac(message, signature, key):
    expected = hmac.new(
        key.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    return Result(value=hmac.compare_digest(expected, signature))


def generate_token(data, secret):
    return hmac.new(
        secret.encode(), data.encode(), hashlib.sha256
    ).hexdigest()
"""
    },
    "auth": {
        "build_type": "macro",
        "service_deps": ["crypto", "config"],
        "internal_deps": ["database", "logging"],
        "code": """\
from monorepo.crypto.module import hash_password, generate_token
from monorepo.config.module import AppConfig
from monorepo.database.module import DatabaseConnection


class AuthManager:
    def __init__(self, config):
        self.config = config
        self.db = DatabaseConnection(config)
        self._sessions = {}

    def authenticate(self, username, password):
        stored_hash = self._get_stored_hash(username)
        if stored_hash and hash_password(password) == stored_hash:
            token = generate_token(username, "secret_key")
            self._sessions[token] = username
            return token
        return None

    def verify_token(self, token):
        return token in self._sessions

    def _get_stored_hash(self, username):
        results = self.db.execute(
            "SELECT hash FROM users WHERE name = ?",
            [username],
        )
        return results[0] if results else None
"""
    },
    "database": {
        "build_type": "macro",
        "service_deps": ["config"],
        "internal_deps": ["logging"],
        "code": """\
from monorepo.config.module import AppConfig
from monorepo.logging.module import Logger


class DatabaseConnection:
    def __init__(self, config):
        self.config = config
        self.logger = Logger("database")
        self._connected = False

    def connect(self):
        self.logger.info("Connecting to database")
        self._connected = True

    def execute(self, query, params=None):
        if not self._connected:
            self.logger.error("Not connected")
            raise RuntimeError("Not connected")
        self.logger.debug(f"Executing: {query}")
        return []

    def close(self):
        self._connected = False
        self.logger.info("Connection closed")
"""
    },
    "cache": {
        "build_type": "standard",
        "build_deps": ["config", "core"],
        "code": """\
from monorepo.config.module import AppConfig

import time


class LRUCache:
    def __init__(self, config, max_size=100):
        self.config = config
        self.max_size = max_size
        self._store = {}
        self._access_order = []
        self.ttl = config.get("cache_ttl", 300)

    def get(self, key):
        entry = self._store.get(key)
        if entry and time.time() - entry["ts"] < self.ttl:
            self._access_order.remove(key)
            self._access_order.append(key)
            return entry["value"]
        return None

    def put(self, key, value):
        if len(self._store) >= self.max_size and key not in self._store:
            evict = self._access_order.pop(0)
            del self._store[evict]
        self._store[key] = {"value": value, "ts": time.time()}
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)
"""
    },
    "api": {
        "build_type": "macro",
        "service_deps": ["auth", "cache", "database"],
        "internal_deps": ["logging"],
        "code": """\
from monorepo.auth.module import AuthManager
from monorepo.database.module import DatabaseConnection
from monorepo.cache.module import LRUCache
from monorepo.logging.module import Logger


class APIServer:
    def __init__(self, config):
        self.auth = AuthManager(config)
        self.db = DatabaseConnection(config)
        self.cache = LRUCache(config)
        self.logger = Logger("api")

    def handle_request(self, method, path, headers=None, body=None):
        token = (headers or {}).get("Authorization")
        if token and not self.auth.verify_token(token):
            self.logger.error(f"Unauthorized: {path}")
            return {"status": 401}

        cached = self.cache.get(f"{method}:{path}")
        if cached and method == "GET":
            return cached

        result = self._route(method, path, body)
        if method == "GET":
            self.cache.put(f"{method}:{path}", result)
        return result

    def _route(self, method, path, body):
        return {"status": 200, "path": path}
"""
    },
    "web": {
        "build_type": "standard",
        "build_deps": ["api", "config"],
        "code": """\
from monorepo.api.module import APIServer
from monorepo.config.module import AppConfig


class WebApplication:
    def __init__(self, config_path=None):
        self.config = AppConfig(config_path)
        self.api = APIServer(self.config)

    def serve(self, host="0.0.0.0", port=8080):
        pass

    def render_template(self, template_name, context=None):
        return f"<html><body>{template_name}</body></html>"
"""
    },
    "worker": {
        "build_type": "macro",
        "service_deps": ["cache", "database", "logging", "scheduler"],
        "internal_deps": [],
        "code": """\
from monorepo.database.module import DatabaseConnection
from monorepo.cache.module import LRUCache
from monorepo.logging.module import Logger
from monorepo.scheduler.module import TaskScheduler


class Worker:
    def __init__(self, config):
        self.db = DatabaseConnection(config)
        self.cache = LRUCache(config)
        self.logger = Logger("worker")
        self.scheduler = TaskScheduler(config)

    def process_task(self, task):
        self.logger.info(f"Processing task: {task}")
        result = self.db.execute(
            "SELECT * FROM tasks WHERE id = ?", [task]
        )
        self.cache.put(f"task:{task}", result)
        return result

    def start(self):
        self.logger.info("Worker started")
"""
    },
    "scheduler": {
        "build_type": "standard",
        "build_deps": ["database", "logging", "worker"],
        "code": """\
from monorepo.database.module import DatabaseConnection
from monorepo.logging.module import Logger
from monorepo.worker.module import Worker


class TaskScheduler:
    def __init__(self, config):
        self.db = DatabaseConnection(config)
        self.logger = Logger("scheduler")
        self._tasks = []

    def schedule(self, task, interval):
        self.logger.info(
            f"Scheduling task: {task} every {interval}s"
        )
        self._tasks.append({"task": task, "interval": interval})

    def dispatch(self, task):
        worker = Worker(self.db.config)
        return worker.process_task(task)

    def get_pending(self):
        return self.db.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'pending'"
        )
"""
    },
    "metrics": {
        "build_type": "standard",
        "build_deps": ["database", "logging"],
        "code": """\
from monorepo.logging.module import Logger
from monorepo.database.module import DatabaseConnection


class MetricsCollector:
    def __init__(self, config):
        self.logger = Logger("metrics")
        self.db = DatabaseConnection(config)
        self._counters = {}

    def increment(self, metric_name, value=1):
        self._counters[metric_name] = (
            self._counters.get(metric_name, 0) + value
        )

    def flush(self):
        for name, value in self._counters.items():
            self.db.execute(
                "INSERT INTO metrics (name, value) VALUES (?, ?)",
                [name, value],
            )
        self.logger.info(f"Flushed {len(self._counters)} metrics")
        self._counters.clear()
"""
    },
    "notification": {
        "build_type": "macro",
        "service_deps": ["auth"],
        "internal_deps": ["logging"],
        "code": """\
from monorepo.auth.module import AuthManager
from monorepo.logging.module import Logger

try:
    from monorepo.crypto.module import generate_token
except ImportError:
    generate_token = None


class NotificationService:
    def __init__(self, config):
        self.auth = AuthManager(config)
        self.logger = Logger("notification")

    def send(self, user_id, message, channel="email"):
        if generate_token is not None:
            token = generate_token(
                f"notif:{user_id}", "notif_secret"
            )
        else:
            token = "unsigned"
        self.logger.info(
            f"Sending {channel} notification to {user_id}: "
            f"{message[:50]}"
        )
        return {"status": "sent", "token": token}

    def broadcast(self, message, channel="push"):
        self.logger.info(
            f"Broadcasting to {channel}: {message[:50]}"
        )
"""
    },
    "search": {
        "build_type": "standard",
        "build_deps": ["cache", "database", "logging", "utils"],
        "code": """\
from monorepo.database.module import DatabaseConnection
from monorepo.cache.module import LRUCache
from monorepo.utils.module import flatten


class SearchEngine:
    def __init__(self, config):
        self.db = DatabaseConnection(config)
        self.cache = LRUCache(config)

    def search(self, query, filters=None):
        cache_key = f"search:{query}:{filters}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        results = self.db.execute(
            "SELECT * FROM documents WHERE content LIKE ?",
            [f"%{query}%"],
        )
        flat_results = flatten(results)
        self.cache.put(cache_key, flat_results)
        return flat_results
"""
    },
    "storage": {
        "build_type": "standard",
        "build_deps": ["crypto", "database", "logging"],
        "code": """\
from monorepo.database.module import DatabaseConnection
from monorepo.crypto.module import hash_password
from monorepo.logging.module import Logger


class StorageBackend:
    def __init__(self, config):
        self.db = DatabaseConnection(config)
        self.logger = Logger("storage")

    def store(self, key, data):
        content_hash = hash_password(str(data), salt=key)
        self.db.execute(
            "INSERT INTO storage (key, hash, data) VALUES (?, ?, ?)",
            [key, content_hash, str(data)],
        )
        self.logger.info(f"Stored object: {key}")

    def retrieve(self, key):
        results = self.db.execute(
            "SELECT data FROM storage WHERE key = ?", [key]
        )
        return results[0] if results else None
"""
    },
    "testing_utils": {
        "build_type": "standard",
        "build_deps": ["config", "core", "utils"],
        "code": """\
from monorepo.core.module import Result
from monorepo.config.module import AppConfig


class MockDatabase:
    def __init__(self):
        self._data = {}

    def execute(self, query, params=None):
        return []

    def seed(self, table, rows):
        self._data[table] = rows


class TestRunner:
    def __init__(self):
        self.config = AppConfig()
        self.results = []

    def assert_ok(self, result):
        if not isinstance(result, Result) or not result.is_ok():
            raise AssertionError(f"Expected Ok, got: {result}")
        self.results.append(("pass", result))
"""
    },
    "analytics": {
        "build_type": "standard",
        "build_deps": ["database", "logging", "metrics", "ml_pipeline"],
        "code": """\
from monorepo.metrics.module import MetricsCollector
from monorepo.database.module import DatabaseConnection
from monorepo.logging.module import Logger
from monorepo.ml_pipeline.module import PipelineExecutor


class AnalyticsEngine:
    def __init__(self, config):
        self.metrics = MetricsCollector(config)
        self.db = DatabaseConnection(config)
        self.logger = Logger("analytics")

    def analyze(self, dataset_id):
        data = self.db.execute(
            "SELECT * FROM datasets WHERE id = ?", [dataset_id]
        )
        self.metrics.increment("analyses_run")
        self.logger.info(f"Analyzing dataset: {dataset_id}")
        return {"dataset_id": dataset_id, "rows": len(data)}

    def run_pipeline(self, pipeline_config):
        executor = PipelineExecutor(self.db.config)
        return executor.execute(pipeline_config)
"""
    },
    "ml_pipeline": {
        "build_type": "standard",
        "build_deps": ["analytics", "database", "logging"],
        "code": """\
from monorepo.database.module import DatabaseConnection
from monorepo.logging.module import Logger
from monorepo.analytics.module import AnalyticsEngine


class PipelineExecutor:
    def __init__(self, config):
        self.db = DatabaseConnection(config)
        self.logger = Logger("ml_pipeline")

    def execute(self, pipeline_config):
        self.logger.info(f"Executing pipeline: {pipeline_config}")
        steps = pipeline_config.get("steps", [])
        results = []
        for step in steps:
            result = self._run_step(step)
            results.append(result)
        return results

    def _run_step(self, step):
        return {"step": step, "status": "completed"}

    def get_analytics(self, config):
        engine = AnalyticsEngine(config)
        return engine.analyze("default")
"""
    },
    "gateway": {
        "build_type": "standard",
        "build_deps": ["api", "auth", "core", "logging", "web"],
        "code": """\
from monorepo.api.module import APIServer
from monorepo.web.module import WebApplication
from monorepo.auth.module import AuthManager
from monorepo.logging.module import Logger


class GatewayServer:
    def __init__(self, config):
        self.api = APIServer(config)
        self.web = WebApplication()
        self.auth = AuthManager(config)
        self.logger = Logger("gateway")

    def route(self, request):
        if request.get("path", "").startswith("/api/"):
            return self.api.handle_request(
                request["method"],
                request["path"],
                request.get("headers"),
                request.get("body"),
            )
        return self.web.render_template("index.html")

    def health_check(self):
        return {"status": "healthy"}
"""
    },
    "report_gen": {
        "build_type": "standard",
        "build_deps": ["analytics"],
        "code": """\
from monorepo.analytics.module import AnalyticsEngine
from monorepo.database.module import DatabaseConnection


class ReportGenerator:
    def __init__(self, config):
        self.analytics = AnalyticsEngine(config)
        self.db = DatabaseConnection(config)

    def generate(self, report_type, params=None):
        params = params or {}
        data = self.analytics.analyze(
            params.get("dataset_id", "default")
        )
        records = self.db.execute(
            "SELECT * FROM report_templates WHERE type = ?",
            [report_type],
        )
        return {
            "type": report_type,
            "data": data,
            "records": len(records),
            "format": "json",
        }

    def list_templates(self):
        return ["summary", "detailed", "executive"]
"""
    },
    "pdf_export": {
        "build_type": "standard",
        "build_deps": ["report_gen"],
        "code": """\
from monorepo.report_gen.module import ReportGenerator


class PDFExporter:
    def __init__(self, config):
        self.report_gen = ReportGenerator(config)

    def export(self, report_type, output_path, params=None):
        report = self.report_gen.generate(
            report_type, params or {}
        )
        content = self._render_pdf(report)
        with open(output_path, "w") as f:
            f.write(content)
        return output_path

    def _render_pdf(self, report):
        return f"PDF_HEADER\\n{report}\\nPDF_FOOTER"
"""
    },
}


def generate_standard_build(name, deps):
    """Generate a standard py_library BUILD file."""
    if deps:
        dep_lines = "\n".join(f'        "//{d}",' for d in sorted(deps))
        deps_block = f"\n{dep_lines}\n    "
    else:
        deps_block = ""

    return (
        f'py_library(\n'
        f'    name = "{name}",\n'
        f'    srcs = ["module.py"],\n'
        f'    deps = [{deps_block}],\n'
        f'    visibility = ["//visibility:public"],\n'
        f')\n'
    )


def generate_macro_build(name, service_deps, internal_deps):
    """Generate a py_service macro BUILD file."""
    lines = ['load("//tools:defs.bzl", "py_service")', '']
    lines.append('py_service(')
    lines.append(f'    name = "{name}",')
    lines.append('    srcs = ["module.py"],')

    if service_deps:
        lines.append('    service_deps = [')
        for d in sorted(service_deps):
            lines.append(f'        "{d}",')
        lines.append('    ],')

    if internal_deps:
        lines.append('    internal_deps = [')
        for d in sorted(internal_deps):
            lines.append(f'        "//{d}",')
        lines.append('    ],')

    lines.append('    visibility = ["//visibility:public"],')
    lines.append(')')
    lines.append('')

    return '\n'.join(lines)


def main():
    os.makedirs(BASE, exist_ok=True)
    with open(os.path.join(BASE, "__init__.py"), "w") as f:
        f.write("")

    # Create tools/defs.bzl (not a package - no BUILD file)
    tools_dir = os.path.join(BASE, "tools")
    os.makedirs(tools_dir, exist_ok=True)
    with open(os.path.join(tools_dir, "defs.bzl"), "w") as f:
        f.write(TOOLS_DEFS_BZL)

    for name, info in sorted(PACKAGES.items()):
        pkg_dir = os.path.join(BASE, name)
        os.makedirs(pkg_dir, exist_ok=True)

        # __init__.py
        with open(os.path.join(pkg_dir, "__init__.py"), "w") as f:
            f.write("")

        # BUILD file
        if info["build_type"] == "macro":
            build_content = generate_macro_build(
                name,
                info["service_deps"],
                info.get("internal_deps", []),
            )
        else:
            build_content = generate_standard_build(
                name,
                info["build_deps"],
            )

        with open(os.path.join(pkg_dir, "BUILD"), "w") as f:
            f.write(build_content)

        # module.py
        with open(os.path.join(pkg_dir, "module.py"), "w") as f:
            f.write(info["code"])

    print(f"Generated {len(PACKAGES)} packages in {BASE}")


if __name__ == "__main__":
    main()
