#!/usr/bin/env python3
"""Web Application Firewall - Multi-layer SQL Injection Detection Engine

Layer 1: YAML-defined rules loaded from configurable config file.
Layer 2: Python-defined regex rules (hardcoded).
Logs all decisions as structured JSON to /var/log/waf/requests.jsonl.
"""

import re
import urllib.parse
import json
import os
from datetime import datetime

try:
    import yaml
except ImportError:
    yaml = None

LOG_PATH = '/var/log/waf/requests.jsonl'


class WAF:
    """Multi-layer regex-based SQL injection detection."""

    PYTHON_RULES = [
        ("P01", r"(?i)\([ \t]*select\b", "Subquery injection"),
        ("P02", r"(?i)\b(char|chr|concat|group_concat)\s*\(", "String function abuse"),
        ("P03", r"(?i)\b0x[0-9a-f]{2,}", "Hex literal injection"),
        ("P04", r"(?i)\b(sleep|benchmark|randomblob)\s*\(", "Timing-based attack"),
        ("P05", r"(?i)\b(drop|alter|create|insert|update|delete|truncate)\b",
         "DDL/DML operation"),
        ("P06", r";", "Statement terminator injection"),
        ("P07", r"(\/\*|\*\/|--)", "SQL comment injection"),
    ]

    def __init__(self, config_path='/app/waf_rules.yaml'):
        self.config_path = config_path
        self.yaml_rules = []
        self.preprocess_config = {}
        self.trusted_headers = []
        self._load_config()

    def _load_config(self):
        """Load YAML rule configuration."""
        if yaml is None:
            return
        if not os.path.exists(self.config_path):
            return
        with open(self.config_path) as f:
            config = yaml.safe_load(f)
        if not config:
            return
        for rule in config.get('rules', []):
            self.yaml_rules.append(
                (rule['id'], rule['pattern'], rule['description']))
        self.preprocess_config = config.get('preprocessing', {})
        self.trusted_headers = config.get('trusted_headers', [])

    def preprocess(self, user_input):
        """Normalize input before rule checking."""
        processed = user_input
        if self.preprocess_config.get('url_decode', True):
            processed = urllib.parse.unquote(processed)
        ws_pattern = self.preprocess_config.get(
            'normalize_whitespace', r'[\t\r\n]')
        processed = re.sub(ws_pattern + '+', ' ', processed)
        if self.preprocess_config.get('strip_nulls', True):
            processed = processed.replace('\x00', '')
        return processed

    def check(self, user_input, headers=None):
        """
        Check input against all WAF rules.

        Returns:
            tuple: (allowed: bool, triggered_rules: list of (rule_id, description))
        """
        processed = self.preprocess(user_input)
        triggered = []

        # Check trusted headers - skip YAML rules if trusted source
        skip_yaml = False
        if headers:
            for th in self.trusted_headers:
                header_val = headers.get(th['name'], '')
                if header_val == th['value']:
                    if th.get('action') == 'skip_yaml_rules':
                        skip_yaml = True
                        break

        # Layer 1: YAML-defined rules
        if not skip_yaml:
            for rule_id, pattern, description in self.yaml_rules:
                if re.search(pattern, processed):
                    triggered.append((rule_id, description))

        # Layer 2: Python-defined rules (always checked)
        for rule_id, pattern, description in self.PYTHON_RULES:
            if re.search(pattern, processed):
                triggered.append((rule_id, description))

        allowed = len(triggered) == 0
        self._log_request(user_input, processed, allowed, triggered, headers)
        return allowed, triggered

    def _log_request(self, raw_input, processed, allowed, triggered, headers):
        """Log WAF decision as structured JSON."""
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "raw_input": raw_input[:500],
            "processed_input": processed[:500],
            "allowed": allowed,
            "triggered_rules": [
                {"id": r[0], "desc": r[1]} for r in triggered
            ],
            "headers": dict(headers) if headers else {}
        }
        with open(LOG_PATH, 'a') as f:
            f.write(json.dumps(entry) + '\n')
