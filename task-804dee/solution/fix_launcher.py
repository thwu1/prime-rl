#!/usr/bin/env python3
"""
Fix the 8 bugs in /app/launcher's precheck validation logic.

"""

LAUNCHER = "/app/launcher"

with open(LAUNCHER) as f:
    src = f.read()

# ── Bug 1: basename does not strip .git suffix ──────────────────────
# basename "$url" returns e.g. "discourse-solved.git" which doesn't
# match the bundled list entry "discourse-solved".
# Fix: basename "$url" .git
src = src.replace(
    'name=$(basename "$url")',
    'name=$(basename "$url" .git)',
)

# ── Bug 2: memory comparison inside subshell ────────────────────────
# The ( ... ) around the if-block creates a subshell; modifications to
# errors/warnings/issues are lost when the subshell exits.
# Fix: remove the subshell parentheses.
src = src.replace(
    """\
    (
        if (( val > cap )); then
            log_error "$fn" "db_shared_buffers ${raw} exceeds 25% of system RAM (max ${cap}MB)"
        fi
    )""",
    """\
    if (( val > cap )); then
        log_error "$fn" "db_shared_buffers ${raw} exceeds 25% of system RAM (max ${cap}MB)"
    fi""",
)

# ── Bug 3: SMTP check only covers port 465 case ────────────────────
# Missing the converse: port 587 uses STARTTLS, so FORCE_TLS=true is
# incorrect there (FORCE_TLS means implicit TLS at connect time).
# Fix: add the 587 + FORCE_TLS check.
src = src.replace(
    '''\
    if [[ "$port" == "465" && "$ftls" != "true" ]]; then
        log_error "$fn" "Port 465 requires DISCOURSE_SMTP_FORCE_TLS=true for implicit TLS"
    fi''',
    '''\
    if [[ "$port" == "465" && "$ftls" != "true" ]]; then
        log_error "$fn" "Port 465 requires DISCOURSE_SMTP_FORCE_TLS=true for implicit TLS"
    fi
    if [[ "$port" == "587" && "$ftls" == "true" ]]; then
        log_error "$fn" "Port 587 uses STARTTLS — DISCOURSE_SMTP_FORCE_TLS must not be true"
    fi''',
)

# ── Bug 4: hostname regex only matches bare example.com ─────────────
# ^example\.(com|org|net)$ won't match "discourse.example.com".
# Fix: allow optional subdomain prefix.
src = src.replace(
    "grep -qE '^example\\.(com|org|net)$'",
    "grep -qE '(^|\\.)example\\.(com|org|net)$'",
)

# ── Bug 5: developer-emails check requires wrong template ──────────
# Looks for 'web.standalone.template.yml' but the actual web container
# uses 'web.template.yml'.
# Fix: match the actual template name.
src = src.replace(
    "web\\.standalone\\.template\\.yml",
    "web\\.template\\.yml",
)

# ── Bug 6: SSL template grep is anchored, misses path prefix ───────
# '^web\.ssl\.template\.yml$' won't match 'templates/web.ssl.template.yml'.
# Fix: drop the anchors.
src = src.replace(
    "'^web\\.ssl\\.template\\.yml$'",
    "'web\\.ssl\\.template\\.yml'",
)

# ── Bug 7: SHM check looks for 'postgresql' instead of 'postgres' ──
# The Discourse template is named postgres.template.yml, not postgresql.
# Fix: correct the name.
src = src.replace(
    "'postgresql\\.template\\.yml'",
    "'postgres\\.template\\.yml'",
)

# ── Bug 8: port-conflict comparison is backwards ────────────────────
# '[ "$fn" = "$other" ]' only fires for same-file duplicates (rare).
# Cross-file conflicts (the real concern) need '!='.
# Fix: invert the condition.
src = src.replace(
    'if [[ "$fn" = "$other" ]]; then\n'
    '                    log_error "$fn" "Host port $p conflicts with $other"',
    'if [[ "$fn" != "$other" ]]; then\n'
    '                    log_error "$fn" "Host port $p conflicts with $other"',
)

with open(LAUNCHER, "w") as f:
    f.write(src)

print("Launcher: all 8 validation bugs fixed.")
