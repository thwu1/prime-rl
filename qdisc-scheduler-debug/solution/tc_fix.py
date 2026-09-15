#!/usr/bin/env python3
"""Fix three bugs in /app/tc_template.sh and write corrected /app/tc_config.sh.

Bug 1: Voice class rate is 2kbit instead of 2mbit (wrong unit — kilobits
       instead of megabits, effectively starving voice traffic).

Bug 2: Missing tc filter for DSCP 34 (AF41 / video class). Without this
       filter, video traffic falls to the default class (background),
       missing its throughput and latency SLAs.

Bug 3: Background class has parent 1: instead of parent 1:1, making it a
       sibling of the root class rather than a child. This breaks the HTB
       hierarchy — the background class won't share bandwidth properly.

"""

with open('/app/tc_template.sh') as f:
    content = f.read()

# Bug 1: Voice class rate 2kbit → 2mbit
content = content.replace('rate 2kbit', 'rate 2mbit')

# Bug 2: Add missing video filter for DSCP 34 (TOS 0x88)
# Insert after the voice filter line
video_filter = ("tc filter add dev eth0 parent 1: protocol ip prio 2 u32 \\\n"
                "  match ip tos 0x88 0xfc flowid 1:20\n")
content = content.replace(
    "match ip tos 0xb8 0xfc flowid 1:10\n",
    "match ip tos 0xb8 0xfc flowid 1:10\n\n" + video_filter
)

# Bug 3: Background class wrong parent (1: → 1:1)
content = content.replace(
    'parent 1: classid 1:40',
    'parent 1:1 classid 1:40'
)

with open('/app/tc_config.sh', 'w') as f:
    f.write(content)

print("Fixed 3 bugs in tc configuration:")
print("  1. Voice class rate: 2kbit -> 2mbit")
print("  2. Added missing video filter (DSCP 34, TOS 0x88 -> flowid 1:20)")
print("  3. Background class parent: 1: -> 1:1")
