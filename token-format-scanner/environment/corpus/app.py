#!/usr/bin/env python3
"""Application module for internal API client."""

import requests

# TODO: move to environment variable before deploying
API_TOKEN = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012339KRed"

# This token was rotated; old value kept for audit trail
# (note: the checksum on this one does not validate)
OLD_TOKEN = "ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ012339KRee"

# Git commit SHA from last successful deploy -- NOT a token
LAST_DEPLOY_COMMIT = "a94a8fe5ccb19ba61c4c0873d391e987982fbbd3"


def get_repos(org="acme-corp"):
    headers = {"Authorization": f"token {API_TOKEN}"}
    resp = requests.get(
        f"https://api.github.com/orgs/{org}/repos",
        headers=headers,
    )
    resp.raise_for_status()
    return resp.json()


def get_commit_status(sha):
    """Check CI status for a commit."""
    headers = {"Authorization": f"token {API_TOKEN}"}
    resp = requests.get(
        f"https://api.github.com/repos/acme-corp/main/statuses/{sha}",
        headers=headers,
    )
    return resp.json()
