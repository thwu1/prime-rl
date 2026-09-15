#!/bin/bash
set -e

mkdir -p /app/repo
cd /app/repo
git init
git config user.email "dev@acme-corp.com"
git config user.name "Developer"

# Commit 1: Initial project setup
cat > README.md << 'READMEEOF'
# acme-service

Internal API service for Acme Corp.

## Setup

1. Clone the repository
2. Copy `.env.example` to `.env` and fill in credentials
3. Run `docker compose up`

## Architecture

The service exposes a REST API on port 8080 and communicates with
GitHub's API for repository management operations.
READMEEOF
git add README.md
git commit -m "Initial commit"

# Commit 2: Developer accidentally adds credentials file
cat > .credentials.yml << 'CREDEOF'
# Service credentials for CI/CD pipeline
# DO NOT COMMIT THIS FILE
github:
  personal_token: "ghp_w9TkR3mNvJ6xYbHf2QdLpS0cGiA5eZ48nwy3"
  app_installation_token: "ghs_n4FyQ8wKtM1vXjRg5BdLpS0cGiA5eZ32mlSA"
aws:
  access_key_id: "AKIAIOSFODNN7EXAMPLE"
  secret_access_key: "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
CREDEOF
git add .credentials.yml
git commit -m "Add service credentials for CI pipeline"

# Commit 3: Security remediation - remove credentials
git rm .credentials.yml
cat >> .gitignore << 'IGNEOF'
.credentials.yml
.env
*.pem
*.key
IGNEOF
git add .gitignore
git commit -m "Remove leaked credentials and add gitignore"

# Commit 4: Add API config with a token (will be amended)
cat > api_config.json << 'APIEOF'
{
  "endpoint": "https://api.github.com",
  "token": "ghu_h2VxN6rKpL9sYhTf3WcJdQ0dHiB5fA4Qf4WR",
  "rate_limit": 5000,
  "timeout_ms": 30000
}
APIEOF
git add api_config.json
git commit -m "Add API configuration"

# Developer realizes the mistake and amends the commit to redact the token
# This creates a dangling commit containing the original token
cat > api_config.json << 'APIEOF2'
{
  "endpoint": "https://api.github.com",
  "token": "REDACTED_USE_ENV_VAR",
  "rate_limit": 5000,
  "timeout_ms": 30000
}
APIEOF2
git add api_config.json
git commit --amend -m "Add API configuration"

# Commit 5: Add auth module — developer stashes WIP containing a token
cat > auth_handler.py << 'AUTHEOF'
"""Authentication handler for staging environment."""
import os

def get_staging_token():
    return os.environ.get("GITHUB_TOKEN", "")
AUTHEOF
git add auth_handler.py
git commit -m "Add auth handler module"

# Now create a stash with a hardcoded staging token
cat > auth_handler.py << 'STASHEOF'
"""Authentication handler for staging environment."""
import os

# FIXME: remove hardcoded token before merge
STAGING_TOKEN = "ghp_v9TkQ8wNpJ6xYbHf5RdLpS0cGiA7eZ4GLs3f"

def get_staging_token():
    return STAGING_TOKEN
STASHEOF
git stash save "WIP: hardcoded staging token for local testing"

# Add a code review note on the first commit containing a deployment bot token
FIRST_COMMIT=$(git rev-list --max-parents=0 HEAD)
git notes add -m "Code review note (2024-03-12): OAuth token for deployment bot account: gho_f4UxP9sKqL8wYhTg3BeLpR0cHiA5fZ24HcZA — flagged for rotation per security policy. Reviewer: @security-team" "$FIRST_COMMIT"
