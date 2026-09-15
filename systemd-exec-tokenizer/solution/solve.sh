#!/bin/bash

set -e

# =============================================================================
# 1. Install the tokenizer
# =============================================================================

# Copy the Python tokenizer engine to /app
cp /solution/sd_tokenize_engine.py /app/sd_tokenize_engine.py

# Create the shell wrapper script
cat > /app/sd_tokenize.sh << 'WRAPPER_EOF'
#!/bin/bash
# systemd ExecStart tokenizer
# Implements tokenization rules from systemd.service(5) and systemd.syntax(7)
#
# Usage: sd_tokenize.sh [FILE]
#   Reads from FILE or stdin. Input contains Environment= and ExecStart= lines.
#   Outputs parsed argument vectors.

exec python3 /app/sd_tokenize_engine.py "$@"
WRAPPER_EOF
chmod +x /app/sd_tokenize.sh

# =============================================================================
# 2. Fix the broken service files
# =============================================================================

mkdir -p /app/fixed/scripts

# ---------------------------------------------------------------------------
# Fix data-pipeline.service
# Bugs: Uses pipe (|) and redirect (>, 2>&1) directly in ExecStart.
#   systemd does NOT interpret these as shell metacharacters — they are
#   passed as literal arguments to process-data.
# Fix: Create a wrapper script that uses shell to handle pipe/redirect.
# ---------------------------------------------------------------------------

cat > /app/fixed/scripts/data-pipeline.sh << 'SCRIPT_EOF'
#!/bin/bash
# Wrapper script for data-pipeline.service
# Runs the processing pipeline with proper shell pipe and redirect support.
/usr/local/bin/process-data --input "${INPUT}" --format csv \
  | /usr/local/bin/transform > "${OUTPUT}" 2>&1
SCRIPT_EOF
chmod +x /app/fixed/scripts/data-pipeline.sh

cat > /app/fixed/data-pipeline.service << 'SVC_EOF'
# Intended behavior: Run process-data reading from INPUT path,
# pipe its output through transform, and save the final result
# to OUTPUT path with stderr merged into stdout.
# Both INPUT and OUTPUT paths must be expanded from environment variables.
[Unit]
Description=Data Processing Pipeline
After=network.target

[Service]
Type=oneshot
Environment="INPUT=/var/data/raw/input.csv"
Environment="OUTPUT=/var/data/processed/output.json"
ExecStart=/bin/sh -c '/usr/local/bin/process-data --input "${INPUT}" --format csv | /usr/local/bin/transform > "${OUTPUT}" 2>&1'

[Install]
WantedBy=multi-user.target
SVC_EOF

# ---------------------------------------------------------------------------
# Fix app-server.service
# Bugs:
#   1. ${JVM_OPTS} keeps all JVM options as ONE argument.
#      Java needs them as separate args -> use $JVM_OPTS (word splitting).
#   2. $CONFIG_FILE splits the path on spaces.
#      Path must be preserved as a single value -> use ${CONFIG_FILE}.
# Fix: Swap $JVM_OPTS and ${CONFIG_FILE}.
# ---------------------------------------------------------------------------

cat > /app/fixed/app-server.service << 'SVC_EOF'
# Intended behavior: Start a Java application server.
# JVM_OPTS contains multiple JVM flags that must be passed as SEPARATE
# arguments to the java command (not as one combined string).
# CONFIG_FILE contains a path with spaces that must be preserved as
# a SINGLE argument to the -Dconfig= option.
[Unit]
Description=Application Server
After=network.target

[Service]
Type=simple
Environment="JVM_OPTS=-Xmx512m -Xms256m -XX:+UseG1GC"
Environment="CONFIG_FILE=/etc/myapp/config dir/app.properties"
ExecStart=/usr/bin/java $JVM_OPTS -Dconfig=${CONFIG_FILE} -jar /opt/app/server.jar
Restart=on-failure

[Install]
WantedBy=multi-user.target
SVC_EOF

# ---------------------------------------------------------------------------
# Fix deploy-hook.service
# Bug: The : prefix on ExecStart suppresses ALL variable expansion.
#   ${VERSION} and ${DEPLOY_COST} won't be expanded — they stay literal.
#   But the intent clearly needs variable expansion.
# Fix: Remove the : prefix.
# ---------------------------------------------------------------------------

cat > /app/fixed/deploy-hook.service << 'SVC_EOF'
# Intended behavior: Run deploy command with the version tag expanded
# from VERSION variable and cost displayed as a dollar amount (e.g. "$500")
# using DEPLOY_COST variable. The - prefix should make failures non-fatal.
# Variable expansion IS needed for both VERSION and DEPLOY_COST.
# The ExecStartPost should notify with the deployed version and cost.
[Unit]
Description=Deployment Notification Hook

[Service]
Type=oneshot
Environment="VERSION=3.2.1"
Environment="DEPLOY_COST=500"
ExecStart=-/usr/local/bin/deploy --tag v${VERSION} --cost $$${DEPLOY_COST}
ExecStartPost=/usr/local/bin/notify --message "Deployed v${VERSION} for $$${DEPLOY_COST}"

[Install]
WantedBy=multi-user.target
SVC_EOF

# ---------------------------------------------------------------------------
# Fix multi-step.service
# Bug: With Type=simple, only ONE ExecStart= is allowed. Multiple ExecStart=
#   lines override each other — only the LAST one runs. The first two init
#   steps (init-db, warm-cache) are silently discarded.
#   Also, the main process (start-app) is long-running, so Type=oneshot is wrong.
# Fix: Move init steps to ExecStartPre=, keep single ExecStart= for main process.
# ---------------------------------------------------------------------------

cat > /app/fixed/multi-step.service << 'SVC_EOF'
# Intended behavior: Run three initialization steps in sequence.
# Step 1: Initialize database schema (short-lived, exits when done)
# Step 2: Warm up cache (short-lived, exits when done)
# Step 3: Start application listener on port 8080 (long-running main process)
# All init steps must complete successfully before the main app starts.
# The service should restart on failure.
[Unit]
Description=Multi-step Application Initialization
After=network.target

[Service]
Type=simple
ExecStartPre=/usr/local/bin/init-db --create-schema
ExecStartPre=/usr/local/bin/warm-cache --preload
ExecStart=/usr/local/bin/start-app --port 8080
Restart=on-failure

[Install]
WantedBy=multi-user.target
SVC_EOF

# ---------------------------------------------------------------------------
# Fix healthcheck.service
# Bugs:
#   1. && in ExecStartPre is NOT a shell operator — systemd passes it as a
#      literal argument to check-deps. Need separate ExecStartPre= lines.
#   2. while/do/done in ExecStartPost is shell syntax — systemd cannot parse
#      it. Need a wrapper script or sh -c invocation.
# Fix: Split ExecStartPre, create wrapper for health check loop.
# ---------------------------------------------------------------------------

cat > /app/fixed/scripts/healthcheck-wait.sh << 'SCRIPT_EOF'
#!/bin/bash
# Wait for the application health endpoint to respond successfully.
# Uses APP_PORT and HEALTH_EP environment variables inherited from the service.
MAX_RETRIES=60
RETRY=0
while [ "$RETRY" -lt "$MAX_RETRIES" ]; do
    if curl -sf "http://localhost:${APP_PORT}${HEALTH_EP}" > /dev/null 2>&1; then
        exit 0
    fi
    RETRY=$((RETRY + 1))
    sleep 1
done
echo "Health check failed after ${MAX_RETRIES} seconds" >&2
exit 1
SCRIPT_EOF
chmod +x /app/fixed/scripts/healthcheck-wait.sh

cat > /app/fixed/healthcheck.service << 'SVC_EOF'
# Intended behavior:
# Pre-start step 1: Check that dependencies are available (short-lived)
# Pre-start step 2: Run database migration (short-lived)
# Main: Start the application as a forking daemon on APP_PORT, writing PID file
# Post-start: Poll the health endpoint in a loop until it responds with HTTP 200
#
# The two pre-start checks must run as separate sequential steps.
# The health check poll requires a shell loop construct.
[Unit]
Description=Health-checked Application
After=network.target

[Service]
Type=forking
PIDFile=/run/myapp.pid
Environment="APP_PORT=8080"
Environment="HEALTH_EP=/healthz"
ExecStartPre=/usr/local/bin/check-deps
ExecStartPre=/usr/local/bin/migrate-db
ExecStart=/usr/local/bin/myapp --port ${APP_PORT} --daemonize --pidfile /run/myapp.pid
ExecStartPost=/app/fixed/scripts/healthcheck-wait.sh

[Install]
WantedBy=multi-user.target
SVC_EOF

echo "Solution applied successfully."
