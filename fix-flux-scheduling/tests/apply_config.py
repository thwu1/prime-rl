#!/usr/bin/env python3

"""
Parse the agent's fixed Flux config and apply it to the running test instance.

In a containerized --test-size=8 environment, all brokers share one system
hostname, so hostname-based resource.config entries cannot be applied directly.
This script translates them to rank-based property assignments using
'flux R set-property', then reloads via 'flux resource reload'.

Queue/policy config is loaded separately via 'flux config load'.

CRITICAL: We use 'flux resource reload FILE' (not 'flux module reload resource
noverify') because the latter restarts the entire resource module, causing it
to lose track of which ranks are online. All ranks appear "down" and the
scheduler cannot place any jobs. 'flux resource reload' sends an RPC to the
running resource module to update R in-place, preserving rank online status.

Follows the pattern from the Flux test suite (t2311-resource-drain.t):
  flux module remove sched-simple
  flux R encode ... >R
  flux resource reload R
  flux module load sched-simple
"""

import json
import os
import re
import subprocess
import sys
import time
import tomllib


def parse_hostlist_to_ranks(hostlist_str):
    """Parse Flux hostlist like 'node[0-7]' or 'node6' into a set of rank ints.

    Assumes nodeN maps to rank N (standard naming for this cluster).
    """
    if not hostlist_str:
        return set()
    ranks = set()
    match = re.match(r'\w+\[([\d,\-]+)\]', hostlist_str)
    if match:
        for part in match.group(1).split(','):
            part = part.strip()
            if '-' in part:
                s, e = part.split('-', 1)
                ranks.update(range(int(s), int(e) + 1))
            else:
                ranks.add(int(part))
        return ranks
    match = re.match(r'\w*?(\d+)$', hostlist_str.strip())
    if match:
        ranks.add(int(match.group(1)))
        return ranks
    return ranks


def ranks_to_idset(ranks):
    """Convert set of rank numbers to idset string like '0-1' or '2-5'."""
    if not ranks:
        return ""
    sr = sorted(ranks)
    ranges = []
    start = end = sr[0]
    for r in sr[1:]:
        if r == end + 1:
            end = r
        else:
            ranges.append(f"{start}-{end}" if start != end else str(start))
            start = end = r
    ranges.append(f"{start}-{end}" if start != end else str(start))
    return ",".join(ranges)


def run(cmd, input_data=None):
    """Run a command, raising on failure."""
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        input=input_data
    )
    if result.returncode != 0:
        print(f"FAILED: {' '.join(cmd)}", file=sys.stderr)
        if result.stderr:
            print(f"  stderr: {result.stderr.strip()}", file=sys.stderr)
        if result.stdout:
            print(f"  stdout: {result.stdout.strip()}", file=sys.stderr)
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")
    return result


def main():
    config_dir = sys.argv[1]

    # --- Read and parse all TOML files in the config directory ---
    full_config = {}
    resource_config_entries = []

    toml_files = sorted(f for f in os.listdir(config_dir) if f.endswith('.toml'))
    if not toml_files:
        print("ERROR: No .toml files found in config directory", file=sys.stderr)
        sys.exit(1)

    for fname in toml_files:
        fpath = os.path.join(config_dir, fname)
        with open(fpath, 'rb') as f:
            try:
                data = tomllib.load(f)
            except Exception as e:
                print(f"ERROR parsing {fpath}: {e}", file=sys.stderr)
                sys.exit(1)

        # Collect [[resource.config]] entries (array of tables)
        rc = data.get('resource', {}).get('config', [])
        if isinstance(rc, dict):
            resource_config_entries.append(rc)
        elif isinstance(rc, list):
            resource_config_entries.extend(rc)

        # Merge top-level keys (resource.config handled above)
        for key, val in data.items():
            if key == 'resource':
                if key not in full_config:
                    full_config[key] = {}
                for rk, rv in val.items():
                    if rk != 'config':
                        full_config[key][rk] = rv
            elif key in full_config and isinstance(full_config[key], dict) and isinstance(val, dict):
                full_config[key].update(val)
            else:
                full_config[key] = val

    # --- Extract property assignments: property -> set of ranks ---
    property_map = {}
    for entry in resource_config_entries:
        hosts = entry.get('hosts', '')
        props = entry.get('properties', [])
        ranks = parse_hostlist_to_ranks(hosts)
        for p in props:
            property_map.setdefault(p, set()).update(ranks)

    # --- Extract resource.exclude ---
    exclude_str = full_config.get('resource', {}).get('exclude', '')
    excluded_ranks = parse_hostlist_to_ranks(exclude_str)

    # --- Extract queue config ---
    queues = full_config.get('queues', {})
    policy = full_config.get('policy', {})
    defaults = policy.get('jobspec', {}).get('defaults', {}).get('system', {})

    # === Build queue/policy TOML (no resource section — applied separately) ===
    lines = ['[access]', 'allow-root-owner = true', '']

    for qname, qcfg in queues.items():
        lines.append(f'[queues.{qname}]')
        if 'requires' in qcfg:
            lines.append(f'requires = {json.dumps(qcfg["requires"])}')
        pol = qcfg.get('policy', {})
        lim = pol.get('limits', {})
        if 'duration' in lim:
            lines.append(f'policy.limits.duration = "{lim["duration"]}"')
        lines.append('')

    if 'queue' in defaults:
        lines.append('[policy.jobspec.defaults.system]')
        lines.append(f'queue = "{defaults["queue"]}"')
        lines.append('')

    queue_toml = '\n'.join(lines)

    # === Apply to running Flux instance ===
    print("Applying agent configuration to test instance...")

    # STEP 1: Load queue/policy config.
    # This configures queue definitions and default queue in the job manager.
    print("  Step 1: Loading queue/policy configuration...")
    run(['flux', 'config', 'load'], input_data=queue_toml)
    print(f"  Loaded queue config: queues={list(queues.keys())}")
    print(f"  Default queue: {defaults.get('queue', 'NOT SET')}")

    # STEP 2: Wait for config propagation to all modules
    time.sleep(1)

    # STEP 3: Unload scheduler so resource changes don't race with scheduling.
    # Pattern from t2311-resource-drain.t in the Flux test suite.
    print("  Step 3: Unloading scheduler...")
    run(['flux', 'module', 'unload', 'sched-simple'])
    print("  Unloaded sched-simple")

    # STEP 4: Get base R from KVS, set properties via flux R set-property
    print("  Step 4: Setting resource properties...")
    base_r = run(['flux', 'kvs', 'get', 'resource.R']).stdout

    if property_map:
        args = []
        for p, r in sorted(property_map.items()):
            if r:
                args.append(f"{p}:{ranks_to_idset(r)}")
        if args:
            result = run(['flux', 'R', 'set-property'] + args,
                         input_data=base_r)
            modified_r = result.stdout
            print(f"  Set properties: {args}")

            # Verify properties were actually set
            try:
                r_json = json.loads(modified_r)
                props = r_json.get('execution', {}).get('properties', {})
                print(f"  Verified properties in R: {list(props.keys())}")
                if not props:
                    print("  WARNING: No properties found in modified R!",
                          file=sys.stderr)
            except (json.JSONDecodeError, KeyError):
                print("  WARNING: Could not verify properties in modified R",
                      file=sys.stderr)
        else:
            modified_r = base_r
            print("  No property assignments found")
    else:
        modified_r = base_r
        print("  WARNING: No resource.config entries with properties found")

    # STEP 5: Reload resources via 'flux resource reload'.
    # This sends the modified R to the running resource module via RPC,
    # updating R in-place WITHOUT restarting the module. This preserves
    # rank online/up status. Also updates resource.R in the KVS.
    #
    # DO NOT use 'flux module reload resource noverify' — that restarts the
    # entire resource module, which loses rank online status and causes all
    # ranks to appear as "down". The scheduler then sees 0 free resources
    # and cannot place any jobs.
    print("  Step 5: Reloading resources via flux resource reload...")
    tmpfile = '/tmp/flux_modified_R.json'
    with open(tmpfile, 'w') as f:
        f.write(modified_r)
    run(['flux', 'resource', 'reload', tmpfile])
    print("  Resources reloaded (rank online status preserved)")

    # STEP 6: Load scheduler fresh — it reads updated R from resource module
    print("  Step 6: Loading scheduler...")
    run(['flux', 'module', 'load', 'sched-simple'])
    print("  Loaded sched-simple")

    # STEP 7: Start and enable all queues.
    # After config changes, queues may be in stopped/disabled state.
    print("  Step 7: Starting and enabling queues...")
    subprocess.run(
        ['flux', 'queue', 'start', '--all'],
        capture_output=True, text=True
    )
    subprocess.run(
        ['flux', 'queue', 'enable', '--all'],
        capture_output=True, text=True
    )
    print("  Started and enabled all queues")

    # STEP 8: Drain any excluded ranks to simulate resource.exclude
    if excluded_ranks:
        for rank in sorted(excluded_ranks):
            subprocess.run(
                ['flux', 'resource', 'drain', str(rank), 'excluded-by-config'],
                capture_output=True
            )
        print(f"  Drained excluded ranks: {sorted(excluded_ranks)}")

    # Wait for scheduler to fully process resource state
    time.sleep(2)

    # === Summary and verification ===
    print(f"\nConfiguration applied:")
    print(f"  Properties: { {k: sorted(v) for k, v in property_map.items()} }")
    print(f"  Excluded:   {sorted(excluded_ranks) if excluded_ranks else 'none'}")
    print(f"  Default Q:  {defaults.get('queue', 'NOT SET')}")
    print(f"  Queues:     {list(queues.keys())}")

    # Verify resource properties visible
    verify = subprocess.run(
        ['flux', 'resource', 'list', '-s', 'all', '-no', '{properties}'],
        capture_output=True, text=True
    )
    if verify.returncode == 0:
        print(f"  Resource properties: {verify.stdout.strip()}")

    # Verify resources are in free state (not down)
    free_check = subprocess.run(
        ['flux', 'resource', 'list', '-s', 'free', '-no', '{nnodes}'],
        capture_output=True, text=True
    )
    if free_check.returncode == 0:
        lines_out = [x.strip() for x in free_check.stdout.strip().split('\n')
                     if x.strip()]
        total_free = sum(int(x) for x in lines_out) if lines_out else 0
        print(f"  Free nodes: {total_free}")
        if total_free == 0:
            print("  ERROR: No free nodes! Checking resource status...",
                  file=sys.stderr)
            status = subprocess.run(
                ['flux', 'resource', 'status'],
                capture_output=True, text=True
            )
            print(f"  {status.stdout}", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
