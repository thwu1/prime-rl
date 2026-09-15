"""
Apply fixes for cascading failure bugs by copying fixed source files.
"""


import shutil
import os

FIXES = [
    ("/solution/fixed_policy_engine.py", "/app/service_control/policy_engine.py"),
    ("/solution/fixed_client.py", "/app/gateway/client.py"),
    ("/solution/fixed_sync.py", "/app/replicator/sync.py"),
]

for src, dst in FIXES:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print(f"Fixed: {dst}")

print("All cascading failure bugs fixed.")
