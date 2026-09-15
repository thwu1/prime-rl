#!/usr/bin/env python3
"""
Prefix Cleanup Task

Automated sub-task that runs periodically to identify and withdraw
BYOIP prefixes that customers have queued for deletion. This replaces
the previous manual process as part of the fail-small initiative.

Queries the API for prefixes pending deletion and withdraws them
along with their service bindings.
"""

import requests
import logging
import os

API_BASE = os.environ.get('API_BASE', 'http://localhost:8080')

logger = logging.getLogger('cleanup_task')


def get_pending_prefixes():
    """Fetch prefixes pending deletion from the API."""
    resp = requests.get(f"{API_BASE}/api/prefixes?pending_delete")
    resp.raise_for_status()
    return resp.json()


def withdraw_prefix(prefix_id):
    """Withdraw a single prefix."""
    resp = requests.post(
        f"{API_BASE}/api/prefixes/withdraw",
        json={"id": prefix_id},
    )
    resp.raise_for_status()
    return resp.json()


def run_cleanup():
    """Execute the cleanup task."""
    logger.info("Starting prefix cleanup task")

    prefixes = get_pending_prefixes()
    logger.info("Found %d prefixes to clean up", len(prefixes))

    withdrawn = 0
    errors = 0

    for prefix in prefixes:
        try:
            withdraw_prefix(prefix['id'])
            withdrawn += 1
            logger.info(
                "Withdrawn prefix %d (%s)", prefix['id'], prefix['cidr'],
            )
        except Exception as e:
            errors += 1
            logger.error("Failed to withdraw prefix %d: %s", prefix['id'], e)

    logger.info("Cleanup complete: %d withdrawn, %d errors", withdrawn, errors)
    return withdrawn, errors


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('/app/logs/pipeline.log'),
        ],
    )
    run_cleanup()
