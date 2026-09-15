#!/usr/bin/env python3
"""Diagnose and fix coherence protocol bugs, fix tool pipeline issues,
implement Upgrade transactions, and generate required outputs.

Three protocol bugs identified:

Bug 1 (bank.py): Bank interleaving extracts bits from the wrong position.
    intlv_low_bit is set to block_bits - 2 instead of block_bits,
    causing bank selection to use bits within the block offset.
    For 64-byte lines, bits [5:4] are always zero for line-aligned
    addresses, mapping everything to bank 0.

Bug 2 (directory.py): GetS handler omits old owner from sharers.
    When the directory transitions from EXCLUSIVE_MODIFIED to SHARED
    on a GetS, the old owner (who transitions M->O) is not added to
    the sharers set.  A subsequent GetM therefore fails to send an
    Inv to the old owner, leaving a stale Owned copy.

Bug 3 (cache.py): Invalidation does not clear the LR/SC reservation.
    When a cache line is invalidated by an Inv or FwdGetM, the
    reservation register is not checked or cleared.  A subsequent
    SC sees reservation_valid == True and incorrectly succeeds.

Tool pipeline issues:

Makefile bug 1: diagram target uses dot -Tpng but names the output
    protocol.svg, producing PNG binary data in a file that tests
    expect to be valid SVG XML.

Makefile bug 2: trace-report target's jq filter references
    .statistics instead of .bank_stats, causing jq to fail on
    null input to to_entries.

gen_diagram.py: Missing Upgrade transitions in both cache and
    directory state transition lists.

New feature (directory.py + simulator.py): Implement Upgrade transaction.
    When a core holds a Shared or Owned copy and wants to write, it
    should issue an Upgrade (invalidation-only, no data transfer)
    instead of a full GetM.
"""


import subprocess


def fix_bank():
    """Fix 1: Correct bank interleaving bit extraction offset.

    The intlv_low_bit must equal block_bits so that bank-selection
    bits start immediately above the block offset.  The buggy code
    subtracts 2, placing the extraction window inside the offset
    field where line-aligned addresses always read zero.
    """
    path = '/app/moesi_sim/bank.py'
    with open(path) as f:
        lines = f.readlines()

    fixed = False
    for i, line in enumerate(lines):
        if 'intlv_low_bit' in line and 'block_bits - 2' in line:
            lines[i] = line.replace('self.block_bits - 2', 'self.block_bits')
            fixed = True
            break

    assert fixed, "bank.py: intlv_low_bit pattern not found"
    with open(path, 'w') as f:
        f.writelines(lines)
    print("[fix 1] bank.py: intlv_low_bit corrected to block_bits")


def fix_directory_and_add_upgrade():
    """Fix 2 + Feature: Repair sharer tracking, add handle_upgrade method.

    Bug 2: When handle_gets transitions EM -> SHARED via forwarding,
    the old owner (now in O state) must be added to the sharers set.
    Otherwise subsequent GetM/Upgrade misses invalidating the old
    owner, producing stale reads.

    Feature: Add handle_upgrade() for S/O -> M transitions that only
    require invalidation, not data transfer.  Integrated before the
    GetM fallback in the simulator's store path.
    """
    path = '/app/moesi_sim/directory.py'
    with open(path) as f:
        lines = f.readlines()

    # --- Fix 2: In handle_gets EM case, add old_owner to sharers ---
    # Unique pattern: entry.sharers.add(requestor) immediately followed
    # by entry.owner = -1 (only in the EM branch of handle_gets).
    sharers_fixed = False
    for i in range(len(lines) - 1):
        if ('entry.sharers.add(requestor)' in lines[i]
                and 'entry.owner = -1' in lines[i + 1]):
            indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
            lines.insert(i + 1, f'{indent}entry.sharers.add(old_owner)\n')
            sharers_fixed = True
            break

    assert sharers_fixed, "directory.py: sharers pattern not found"
    print("[fix 2] directory.py: old owner added to sharers on EM->S")

    # --- Feature: Insert handle_upgrade method before handle_putm ---
    upgrade_src = [
        '    def handle_upgrade(self, block_addr, requestor):\n',
        '        """Process an Upgrade request (S/O -> M without data transfer).\n',
        '\n',
        '        Returns (inv_targets, actions) on success, or (None, None)\n',
        '        if the upgrade cannot be processed (caller falls back to GetM).\n',
        '        """\n',
        '        entry = self.get_entry(block_addr)\n',
        '\n',
        '        if entry.state != DirState.SHARED or requestor not in entry.sharers:\n',
        '            return None, None\n',
        '\n',
        '        self.stats["upgrade"] = self.stats.get("upgrade", 0) + 1\n',
        '        inv_targets = entry.sharers - {requestor}\n',
        '        actions = [("inv", sharer, block_addr) for sharer in inv_targets]\n',
        '        entry.state = DirState.EXCLUSIVE_MODIFIED\n',
        '        entry.owner = requestor\n',
        '        entry.sharers.clear()\n',
        '        return inv_targets, actions\n',
        '\n',
    ]

    upgrade_added = False
    for i, line in enumerate(lines):
        if 'def handle_putm(self' in line:
            for j, ul in enumerate(upgrade_src):
                lines.insert(i + j, ul)
            upgrade_added = True
            break

    assert upgrade_added, "directory.py: handle_putm anchor not found"
    print("[feat] directory.py: handle_upgrade method added")

    with open(path, 'w') as f:
        f.writelines(lines)


def fix_cache():
    """Fix 3: Clear LR/SC reservation when a line is invalidated.

    The invalidate() method must check whether the invalidated
    block matches the outstanding reservation address.  Without
    this, an SC can succeed after another core wrote to (and
    invalidated) the reserved block.
    """
    path = '/app/moesi_sim/cache.py'
    with open(path) as f:
        lines = f.readlines()

    fixed = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == 'line.state = CacheState.INVALID':
            indent = line[:len(line) - len(line.lstrip())]
            reservation_clear = (
                f'{indent}if (self.reservation_valid and\n'
                f'{indent}        self._block_addr(self.reservation_addr)\n'
                f'{indent}        == self._block_addr(addr)):\n'
                f'{indent}    self.reservation_valid = False\n'
            )
            lines.insert(i + 1, reservation_clear)
            fixed = True
            break

    assert fixed, "cache.py: invalidation pattern not found"
    with open(path, 'w') as f:
        f.writelines(lines)
    print("[fix 3] cache.py: reservation cleared on line invalidation")


def fix_simulator():
    """Feature: Add Upgrade path to store() before GetM fallback.

    When the requesting core already holds the line in Shared or
    Owned state, attempt a directory Upgrade first.  This avoids
    a redundant data transfer that GetM would cause.  If the
    Upgrade cannot be processed (directory out of sync), fall
    through to the existing GetM path.
    """
    path = '/app/moesi_sim/simulator.py'
    with open(path) as f:
        lines = f.readlines()

    upgrade_code = [
        '        # Upgrade from Shared/Owned (no data transfer needed)\n',
        '        if line is not None and line.state in (CacheState.SHARED, CacheState.OWNED):\n',
        '            dir_ctrl = self._get_dir(addr)\n',
        '            upg_result = dir_ctrl.handle_upgrade(block_addr, core_id)\n',
        '            if upg_result[0] is not None:\n',
        '                _, upg_actions = upg_result\n',
        '                for action_type, target, target_block in upg_actions:\n',
        '                    fwd_addr = target_block << self.block_bits\n',
        '                    if action_type == "inv":\n',
        '                        self.caches[target].invalidate(fwd_addr)\n',
        '                line.state = CacheState.MODIFIED\n',
        '                line.data = data\n',
        '                cache.touch_lru(cache._set_index(addr), way)\n',
        '                return\n',
        '\n',
    ]

    inserted = False
    for i, line in enumerate(lines):
        if '# Need exclusive ownership from directory' in line:
            for j, cl in enumerate(upgrade_code):
                lines.insert(i + j, cl)
            inserted = True
            break

    assert inserted, "simulator.py: GetM anchor comment not found"
    with open(path, 'w') as f:
        f.writelines(lines)
    print("[feat] simulator.py: Upgrade path added to store()")


def fix_makefile():
    """Fix Makefile: correct Graphviz output format and jq field references.

    Bug 1: diagram target uses 'dot -Tpng' but output is protocol.svg.
    This produces PNG binary data in a file expected to contain SVG XML.
    Fix: change -Tpng to -Tsvg.

    Bug 2: trace-report target's jq filter references '.statistics'
    but the JSON output from run_sim.py uses '.bank_stats'.
    Fix: replace .statistics with .bank_stats in the jq filter.
    """
    path = '/app/Makefile'
    with open(path) as f:
        content = f.read()

    content = content.replace('dot -Tpng', 'dot -Tsvg')
    content = content.replace('.statistics', '.bank_stats')

    with open(path, 'w') as f:
        f.write(content)
    print("[fix] Makefile: corrected dot format flag and jq field references")


def update_gen_diagram():
    """Add Upgrade transitions to the protocol state diagram generator.

    gen_diagram.py is missing Upgrade transitions in both the cache
    state and directory state transition lists.  These must be added
    to reflect the newly implemented Upgrade protocol support.
    """
    path = '/app/gen_diagram.py'
    with open(path) as f:
        content = f.read()

    # Add Upgrade cache transitions after the GetM Owned->Modified entry
    cache_upgrades = (
        '    ("Shared", "Modified", "Upgrade"),\n'
        '    ("Owned", "Modified", "Upgrade"),\n'
    )
    content = content.replace(
        '    ("Owned", "Modified", "GetM"),\n',
        '    ("Owned", "Modified", "GetM"),\n' + cache_upgrades,
    )

    # Add Upgrade directory transition after the GetM Shared->ExclMod entry
    dir_upgrade = '    ("Shared", "ExclMod", "Upgrade"),\n'
    content = content.replace(
        '    ("Shared", "ExclMod", "GetM"),\n',
        '    ("Shared", "ExclMod", "GetM"),\n' + dir_upgrade,
    )

    with open(path, 'w') as f:
        f.write(content)
    print("[fix] gen_diagram.py: added Upgrade transitions")


def run_make_targets():
    """Run make targets to generate diagram and trace report."""
    for target in ['diagram', 'trace-report']:
        result = subprocess.run(
            ['make', target], cwd='/app',
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"make {target} FAILED:")
            print(f"  stdout: {result.stdout}")
            print(f"  stderr: {result.stderr}")
            raise RuntimeError(f"make {target} failed")
        print(f"[make] {target}: OK")


if __name__ == '__main__':
    # Remove stale bytecode caches before modifying source
    subprocess.run(
        ['find', '/app', '-type', 'd', '-name', '__pycache__',
         '-exec', 'rm', '-rf', '{}', '+'],
        stderr=subprocess.DEVNULL,
    )

    # Phase 1: Fix protocol bugs and implement Upgrade
    fix_bank()
    fix_directory_and_add_upgrade()
    fix_cache()
    fix_simulator()

    # Phase 2: Fix tool pipeline
    fix_makefile()
    update_gen_diagram()

    # Remove stale bytecode caches after source modifications
    subprocess.run(
        ['find', '/app', '-type', 'd', '-name', '__pycache__',
         '-exec', 'rm', '-rf', '{}', '+'],
        stderr=subprocess.DEVNULL,
    )

    # Phase 3: Generate outputs via make
    run_make_targets()

    print("\nAll protocol bugs fixed, Upgrade implemented, and outputs generated.")
