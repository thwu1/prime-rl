#!/usr/bin/env python3
"""Tune /etc/suricata/suricata.yaml for container environments.

Sets runmode to 'single' to avoid thread-pool allocation failures
in memory-constrained containers.
"""
import re

path = '/etc/suricata/suricata.yaml'
with open(path) as f:
    text = f.read()

# Set runmode to single-threaded (avoids pool-thread allocation issues)
if re.search(r'^#?\s*runmode:', text, re.MULTILINE):
    text = re.sub(
        r'^#?\s*runmode:.*$', 'runmode: single',
        text, count=1, flags=re.MULTILINE,
    )
else:
    text += '\nrunmode: single\n'

with open(path, 'w') as f:
    f.write(text)

print("Suricata config tuned: runmode set to single")
