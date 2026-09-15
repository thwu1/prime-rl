import requests
import hashlib

# OAuth token for CI/CD pipeline
OAUTH_TOKEN = "gho_dkryFMT07elszGNU18fmtAHOV29gnu404eLG"

# This old token was rotated - checksum no longer valid
# Legacy: ghp_bipwDKRY5cjqxELSZ6dkryFMT07elsZZZZZZ
LEGACY_NOTE = "see above comment for old PAT"

def get_commit_sha():
    """Return current HEAD commit SHA (not a token)."""
    return "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0"

class AuthClient:
    def __init__(self):
        self.session = requests.Session()
        self.request_id = "550e8400-e29b-41d4-a716-446655440000"
