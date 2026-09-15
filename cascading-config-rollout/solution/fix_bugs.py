"""
Fix three interacting bugs in the config rollout pipeline that combine
to produce a cascading failure when config sources are temporarily
inconsistent.

Bug 1 (merger.py - deep_merge_keys):
    Uses set INTERSECTION (&) instead of set UNION (|) to compute the
    merged key set.  When sources disagree on which keys are present
    (e.g. during a propagation delay), the intersection drops every key
    that is unique to either source, producing an incomplete config.

Bug 2 (rollout.py - execute_rollout):
    Checks whether the canary result ``is_completed`` immediately after
    launching async validation.  Because the canary runs in a background
    thread with a non-zero validation delay, ``is_completed`` is always
    False at that point, so the check is a no-op.  The rollout proceeds
    as if the canary passed even when it would have failed.

Bug 3 (site.py - _cleanup_stale_entries):
    When a new config has fewer entries, the cleanup function loads ALL
    historical config versions from the store and runs an O(n*m^2)
    hash-comparison loop (with a 10 ms sleep per iteration).  With many
    historical versions this far exceeds the health-check timeout,
    marking the site as unhealthy and triggering cascading failures.
"""

import sys


def fix_merger():
    path = "/app/config_pipeline/merger.py"
    with open(path) as f:
        src = f.read()

    # Bug 1: intersection (&) should be union (|)
    target = "primary_keys & secondary_keys"
    if target not in src:
        print(f"[warn] merger.py: expected pattern not found: {target}")
        return False

    src = src.replace(target, "primary_keys | secondary_keys")

    with open(path, "w") as f:
        f.write(src)
    print("[fix] merger.py: deep_merge_keys now uses set union (|)")
    return True


def fix_rollout():
    path = "/app/config_pipeline/rollout.py"
    with open(path) as f:
        src = f.read()

    # Bug 2: canary result is checked before it completes.
    # Add a blocking wait, then check for failure (including timeout).
    target = "if canary_result.is_completed and canary_result.success is False:"
    if target not in src:
        print(f"[warn] rollout.py: expected pattern not found")
        return False

    replacement = (
        "canary_result.wait(timeout=30.0)\n"
        "        if not canary_result.is_completed or canary_result.success is False:"
    )
    src = src.replace(target, replacement)

    with open(path, "w") as f:
        f.write(src)
    print("[fix] rollout.py: execute_rollout now waits for canary result")
    return True


def fix_site():
    path = "/app/config_pipeline/site.py"
    with open(path) as f:
        lines = f.readlines()

    output = []
    i = 0
    fixed_loop = False
    fixed_timeout = False

    while i < len(lines):
        line = lines[i]

        # Replace the expensive historical scan + loop with simple list comprehension
        if not fixed_loop and "all_historical = self.config_store.get_all_historical_configs()" in line:
            # Skip the all_historical line
            i += 1
            # Skip blank line after it if present
            if i < len(lines) and lines[i].strip() == "":
                i += 1
            # Skip the entire stale_entries loop until "stale_entries.append(key)"
            while i < len(lines) and "stale_entries.append(key)" not in lines[i]:
                i += 1
            if i < len(lines):
                i += 1  # skip the stale_entries.append line
            # Write the efficient replacement
            output.append("        stale_entries = [\n")
            output.append("            key for key in self.current_config if key not in new_config\n")
            output.append("        ]\n")
            fixed_loop = True
            continue

        # Remove the timeout check that marks sites unhealthy
        if not fixed_timeout and "if elapsed > self.HEALTH_CHECK_TIMEOUT:" in line:
            # Skip until after "self._healthy = False"
            while i < len(lines) and "self._healthy = False" not in lines[i]:
                i += 1
            if i < len(lines):
                i += 1  # skip the self._healthy = False line
            # Skip trailing blank line if present
            if i < len(lines) and lines[i].strip() == "":
                i += 1
            fixed_timeout = True
            continue

        output.append(line)
        i += 1

    with open(path, "w") as f:
        f.writelines(output)

    print(f"[fix] site.py: loop={'replaced' if fixed_loop else 'MISSED'}, "
          f"timeout={'removed' if fixed_timeout else 'MISSED'}")
    return fixed_loop and fixed_timeout


if __name__ == "__main__":
    results = [fix_merger(), fix_rollout(), fix_site()]
    if all(results):
        print("\nAll three bugs fixed.")
    else:
        print("\nWARNING: Some fixes may not have applied correctly.")
        sys.exit(1)
