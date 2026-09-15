#!/usr/bin/env python3
"""API Gateway - Entry point for all client API requests.

Routes incoming requests through the Service Control layer for quota and
policy enforcement before forwarding them to backend services.  If Service
Control is unavailable the gateway returns 503.
"""
import os
import logging
import requests as http_requests
from flask import Flask, request, jsonify

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('/app/logs/gateway.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('gateway')

SERVICE_CONTROL_URLS = [
    'http://localhost:5001',
    'http://localhost:5002',
    'http://localhost:5003',
]


def _check_with_service_control(service, action, project_id):
    """Call Service Control to validate the request.

    Tries each regional instance in order; returns the first successful
    response.  Returns None if all instances are unreachable.
    """
    for url in SERVICE_CONTROL_URLS:
        try:
            resp = http_requests.post(
                f'{url}/check_quota',
                json={
                    'service': service,
                    'project_id': project_id,
                },
                timeout=2,
            )
            return resp
        except Exception as exc:
            logger.error(
                f"Failed to reach service_control at {url}: {exc}"
            )
    return None


@app.route('/health', methods=['GET'])
def health():
    """Gateway health check."""
    return jsonify({"status": "healthy", "component": "gateway"})


@app.route('/api/<service>/<action>', methods=['POST'])
def handle_api(service, action):
    """Route an API request through Service Control."""
    project_id = request.headers.get('X-Project-ID', 'unknown')

    sc_response = _check_with_service_control(service, action, project_id)
    if sc_response is None:
        logger.error("Returning 503 to client - service_control unavailable")
        return jsonify({
            "error": "SERVICE_UNAVAILABLE",
            "message": "Service Control is currently unavailable",
        }), 503

    if sc_response.status_code == 429:
        return jsonify(sc_response.json()), 429

    if sc_response.status_code != 200:
        return jsonify(sc_response.json()), sc_response.status_code

    # In a real system this would forward to the backend service.
    return jsonify({
        "status": "ok",
        "service": service,
        "action": action,
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
