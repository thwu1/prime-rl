#!/usr/bin/env python3
"""Fix all four bugs in collector.c:
1. Add line-buffered logging (setlinebuf) so logs survive SIGKILL
2. Add maximum message size validation before malloc
3. Fix memory leak on truncation error path (free buf before return)
4. Fix socket FD leak on truncation error path (close sock before return)
"""

import sys

with open('/app/collector.c', 'r') as f:
    source = f.read()

# ---- Bug 1: Add line-buffered logging ----
# Add setlinebuf(logfp) after the fopen / stderr fallback block
old_logfp = (
    '    logfp = fopen(LOG_PATH, "a");\n'
    '    if (!logfp) {\n'
    '        logfp = stderr;\n'
    '    }'
)

new_logfp = (
    '    logfp = fopen(LOG_PATH, "a");\n'
    '    if (!logfp) {\n'
    '        logfp = stderr;\n'
    '    }\n'
    '    setlinebuf(logfp);'
)

if old_logfp in source:
    source = source.replace(old_logfp, new_logfp)
else:
    print("WARNING: Could not find logfp init block to patch", file=sys.stderr)

# ---- Bug 2: Add max payload size constant ----
if 'MAX_PAYLOAD_SIZE' not in source:
    source = source.replace(
        '#define RECV_TIMEOUT_SEC 5',
        '#define RECV_TIMEOUT_SEC 5\n#define MAX_PAYLOAD_SIZE 10485760  /* 10 MB */'
    )

# ---- Bug 2: Add size validation before malloc ----
old_alloc = (
    '    log_msg("Service %s reports payload size: %u bytes", ep->name, msg_len);\n'
    '\n'
    '    /* Allocate buffer for payload */\n'
    '    char *buf = (char *)malloc(msg_len);'
)

new_alloc = (
    '    log_msg("Service %s reports payload size: %u bytes", ep->name, msg_len);\n'
    '\n'
    '    /* Validate message size before allocating */\n'
    '    if (msg_len > MAX_PAYLOAD_SIZE) {\n'
    '        log_msg("Rejecting oversized payload from %s: %u bytes exceeds limit",\n'
    '                ep->name, msg_len);\n'
    '        close(sock);\n'
    '        return -1;\n'
    '    }\n'
    '\n'
    '    /* Allocate buffer for payload */\n'
    '    char *buf = (char *)malloc(msg_len);'
)

if old_alloc in source:
    source = source.replace(old_alloc, new_alloc)
else:
    print("WARNING: Could not find malloc block to patch", file=sys.stderr)

# ---- Bugs 3 & 4: Fix memory leak AND socket leak on truncation error path ----
old_trunc = (
    '            log_msg("Truncated data from %s: got %d of %u bytes",\n'
    '                    ep->name, total, msg_len);\n'
    '            return -1;'
)

new_trunc = (
    '            log_msg("Truncated data from %s: got %d of %u bytes",\n'
    '                    ep->name, total, msg_len);\n'
    '            free(buf);\n'
    '            close(sock);\n'
    '            return -1;'
)

if old_trunc in source:
    source = source.replace(old_trunc, new_trunc)
else:
    print("WARNING: Could not find truncation block to patch", file=sys.stderr)

with open('/app/collector.c', 'w') as f:
    f.write(source)

print("Fixed collector.c: added setlinebuf, MAX_PAYLOAD_SIZE check, "
      "and fixed memory+fd leak on error path")
