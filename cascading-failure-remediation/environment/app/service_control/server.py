#!/usr/bin/env python3
"""Service Control - API policy and quota enforcement service.

This service validates API requests against configured quota limits and access
policies. It reads policy data from regional SQLite databases and enforces
checks on every inbound API request routed through the gateway.

Environment variables:
  INSTANCE_ID - Unique identifier for this instance (used in logging)
  REGION      - Regional database to connect to (region1, region2, region3)
  PORT        - Port to listen on (default: 5001)
"""
import os
import sys
import json
import logging
from flask import Flask, request, jsonify
from policy_loader import PolicyLoader
from feature_flags import FeatureFlags

app = Flask(__name__)

log_dir = '/app/logs'
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(
            os.path.join(log_dir, f'service_control_{os.getenv("INSTANCE_ID", "0")}.log')
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('service_control')

# Global state
policy_cache = {}
flags = None
loader = None


def initialize():
    """Initialize service control on startup.

    Loads all policy records from the regional database into an in-memory
    cache. If initialization fails the process exits so that the supervisor
    can restart it.
    """
    global policy_cache, flags, loader

    region = os.getenv('REGION', 'region1')
    db_path = f'/app/data/policies_{region}.db'

    logger.info(f"Initializing Service Control for region: {region}")
    logger.info(f"Loading policies from: {db_path}")

    flags = FeatureFlags('/app/config/flags.yaml')
    loader = PolicyLoader(db_path, flags)

    # Load all policies into cache on startup
    policy_cache = loader.load_all_policies()
    logger.info(f"Loaded {len(policy_cache)} policies into cache")


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "policies_loaded": len(policy_cache)})


@app.route('/check_quota', methods=['POST'])
def check_quota():
    """Check whether a project has remaining quota for a service."""
    data = request.get_json(force=True)
    service = data.get('service', '')
    project_id = data.get('project_id', '')

    policy = policy_cache.get(service)
    if policy is None:
        # No policy configured - allow by default
        return jsonify({"allowed": True, "reason": "no_policy_configured"})

    if policy.get('quota_remaining', 0) > 0:
        return jsonify({"allowed": True, "quota_remaining": policy['quota_remaining']})
    else:
        return jsonify({"allowed": False, "reason": "quota_exceeded"}), 429


@app.route('/check_policy', methods=['POST'])
def check_policy():
    """Check whether an action is allowed by the service's access policy."""
    data = request.get_json(force=True)
    service = data.get('service', '')
    action = data.get('action', '')

    policy = policy_cache.get(service)
    if policy is None:
        return jsonify({"allowed": True, "reason": "no_policy_configured"})

    allowed_actions = policy.get('allowed_actions', [])
    if action in allowed_actions or '*' in allowed_actions:
        return jsonify({"allowed": True})
    else:
        return jsonify({"allowed": False, "reason": "action_not_allowed"}), 403


if __name__ == '__main__':
    initialize()
    port = int(os.getenv('PORT', 5001))
    app.run(host='0.0.0.0', port=port)
