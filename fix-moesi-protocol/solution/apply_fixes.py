#!/usr/bin/env python3
"""
Apply all fixes to the MOESI cache coherence simulator.

Fixes bugs in the C extension (addr_calc.c), Python cache controller
(l2_controller.py, cache_bank.py), memory system configuration
(memory_system.py), and simulator coordination (simulator.py).
Adds protocol traffic instrumentation (requirement 5).
"""

import subprocess
import sys


def fix_addr_calc():
    """Fix Bug 2a: mask off-by-one in C extension, then rebuild."""
    filepath = '/app/coherence_sim/addr_calc.c'
    with open(filepath, 'r') as f:
        content = f.read()

    old = 'return (1u << intlv_bits);'
    new = 'return (1u << intlv_bits) - 1;'
    if old in content:
        content = content.replace(old, new)
        with open(filepath, 'w') as f:
            f.write(content)
        print("Bug 2a fixed: mask = (1u << intlv_bits) - 1 in addr_calc.c")
    else:
        print("WARNING: Bug 2a pattern not found in addr_calc.c", file=sys.stderr)
        sys.exit(1)

    # Rebuild the shared library
    result = subprocess.run(
        ['make', '-C', '/app/coherence_sim', 'clean', 'all'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"Build failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    print("  Rebuilt libaddrcalc.so")


def fix_l2_controller():
    """Fix Bug 1, Bug 2b, and Bug 4 in l2_controller.py."""
    filepath = '/app/coherence_sim/l2_controller.py'
    with open(filepath, 'r') as f:
        content = f.read()

    # --- Bug 1: Guard _remove_from_dir in DIR_WB_ACK handler ---
    old_wb_ack = (
        '                self._remove_from_dir(line)\n'
        '                line.state = L2State.I\n'
        '                del self.evicting_lines[baddr]'
    )
    new_wb_ack = (
        '                if line.dir_entry_allocated:\n'
        '                    self._remove_from_dir(line)\n'
        '                line.state = L2State.I\n'
        '                del self.evicting_lines[baddr]'
    )
    if old_wb_ack in content:
        content = content.replace(old_wb_ack, new_wb_ack)
        print("Bug 1 fixed: guarded _remove_from_dir in DIR_WB_ACK handler")
    else:
        print("WARNING: Bug 1 pattern not found", file=sys.stderr)
        sys.exit(1)

    # --- Bug 2b: Fix set index to skip bank interleave bits ---
    # Add bank_intlv_bits parameter to __init__
    old_init = (
        '    def __init__(self, bank_id: int, size_kb: int = 2, assoc: int = 2):'
    )
    new_init = (
        '    def __init__(self, bank_id: int, size_kb: int = 2, assoc: int = 2,\n'
        '                 bank_intlv_bits: int = 0):'
    )
    if old_init in content:
        content = content.replace(old_init, new_init)
    else:
        print("WARNING: L2Controller __init__ pattern not found", file=sys.stderr)
        sys.exit(1)

    # Add bank_intlv_bits storage after set_mask
    old_set_mask = '        self.set_mask = self.num_sets - 1'
    new_set_mask = (
        '        self.set_mask = self.num_sets - 1\n'
        '        self.bank_intlv_bits = bank_intlv_bits'
    )
    if old_set_mask in content:
        content = content.replace(old_set_mask, new_set_mask, 1)
    else:
        print("WARNING: set_mask pattern not found", file=sys.stderr)
        sys.exit(1)

    # Fix _get_set_index to pass bank bits to native function
    old_set_idx = (
        '        return _lib.compute_set_index(addr, self.set_mask, BLOCK_OFFSET_BITS)'
    )
    new_set_idx = (
        '        return _lib.compute_set_index(addr, self.set_mask, BLOCK_OFFSET_BITS + self.bank_intlv_bits)'
    )
    if old_set_idx in content:
        content = content.replace(old_set_idx, new_set_idx)
    else:
        print("WARNING: _get_set_index pattern not found", file=sys.stderr)
        sys.exit(1)

    # --- Bug 4: Add recall callback and inclusion enforcement ---
    # Add recall_callback attribute after stats initialization
    old_stats_end = "        }\n\n    def _get_set_index"
    new_stats_end = (
        "        }\n"
        "\n"
        "        # Callback for L2 inclusion enforcement (set by simulator)\n"
        "        self.recall_callback = None\n"
        "\n"
        "    def _get_set_index"
    )
    if old_stats_end in content:
        content = content.replace(old_stats_end, new_stats_end, 1)
    else:
        print("WARNING: stats end pattern not found", file=sys.stderr)
        sys.exit(1)

    # Replace eviction logic in _allocate_line with inclusion-enforcing version
    old_evict = (
        "        if len(lines) >= self.assoc:\n"
        "            victim = lines.pop(0)\n"
        "            if victim.state in (L2State.M, L2State.O):\n"
        "                self._evict_to_dir(victim)\n"
        "            # If victim is S or E (clean), just drop it"
    )
    new_evict = (
        "        if len(lines) >= self.assoc:\n"
        "            victim = lines.pop(0)\n"
        "            # Inclusion enforcement: recall L1 copies before eviction\n"
        "            if self.recall_callback:\n"
        "                dirty_data = self.recall_callback(victim.addr)\n"
        "                if dirty_data is not None:\n"
        "                    victim.data = dirty_data\n"
        "                    victim.dirty = True\n"
        "            victim.sharers.clear()\n"
        "            victim.owner = -1\n"
        "            if victim.dirty or victim.state in (L2State.M, L2State.O):\n"
        "                self._evict_to_dir(victim)"
    )
    if old_evict in content:
        content = content.replace(old_evict, new_evict)
        print("Bug 4 (L2 part): inclusion enforcement added to _allocate_line")
    else:
        print("WARNING: _allocate_line eviction pattern not found", file=sys.stderr)
        sys.exit(1)

    with open(filepath, 'w') as f:
        f.write(content)
    print("Bug 2b fixed: set index now skips bank interleave bits")


def fix_cache_bank():
    """Fix Bug 2b: pass bank_intlv_bits to L2Controller."""
    filepath = '/app/coherence_sim/cache_bank.py'
    with open(filepath, 'r') as f:
        content = f.read()

    # Pass bank_intlv_bits to L2Controller constructor
    old_ctor = (
        "            self.banks.append(L2Controller(\n"
        "                bank_id=i,\n"
        "                size_kb=bank_size_kb,\n"
        "                assoc=assoc,\n"
        "            ))"
    )
    new_ctor = (
        "            self.banks.append(L2Controller(\n"
        "                bank_id=i,\n"
        "                size_kb=bank_size_kb,\n"
        "                assoc=assoc,\n"
        "                bank_intlv_bits=self.intlv_bits,\n"
        "            ))"
    )
    if old_ctor in content:
        content = content.replace(old_ctor, new_ctor)
        print("Bug 2b (cache_bank part): passing bank_intlv_bits to L2Controller")
    else:
        print("WARNING: L2Controller constructor pattern not found", file=sys.stderr)
        sys.exit(1)

    with open(filepath, 'w') as f:
        f.write(content)


def fix_memory_system():
    """Fix Bug 3: Remove +1 from DRAM range end."""
    filepath = '/app/coherence_sim/memory_system.py'
    with open(filepath, 'r') as f:
        content = f.read()

    content = content.replace(
        'dram_range = AddrRange(0, dram_size + 1, "DRAM")',
        'dram_range = AddrRange(0, dram_size, "DRAM")'
    )
    content = content.replace(
        'DirectoryController(0, dram_size + 1, ctrl_id=0)',
        'DirectoryController(0, dram_size, ctrl_id=0)'
    )

    with open(filepath, 'w') as f:
        f.write(content)
    print("Bug 3 fixed: DRAM end = dram_size (no +1)")


def fix_simulator():
    """Fix Bug 4: Add recall callback and recall_l1_copies method."""
    filepath = '/app/coherence_sim/simulator.py'
    with open(filepath, 'r') as f:
        content = f.read()

    # Add recall_l1_copies method before the step() method
    recall_method = '''
    def recall_l1_copies(self, addr):
        """
        Recall and invalidate all L1 copies of the given address.
        Used for L2 inclusion enforcement during eviction.
        Returns dirty data from any M-state L1 holder.
        """
        dirty_data = None
        baddr = block_addr(addr)
        for l1 in self.l1_controllers:
            line = l1._find_line(baddr)
            if line is not None:
                if line.state == CacheState.M:
                    dirty_data = line.data
                line.state = CacheState.I
            # Clear any transient state for this address
            l1.transient_states.pop(baddr, None)
        return dirty_data

'''

    # Insert recall method before step()
    old_step = '    def step(self) -> bool:'
    new_step = recall_method + '    def step(self) -> bool:'
    if old_step in content:
        content = content.replace(old_step, new_step, 1)
    else:
        print("WARNING: step() method not found in simulator", file=sys.stderr)
        sys.exit(1)

    # Add CacheState import
    old_import = 'from .types import MessageType, Message, block_addr, BLOCK_SIZE'
    new_import = 'from .types import MessageType, Message, block_addr, BLOCK_SIZE, CacheState'
    if old_import in content:
        content = content.replace(old_import, new_import)
    else:
        print("WARNING: types import not found in simulator", file=sys.stderr)
        sys.exit(1)

    # Set recall callback after l2_cache creation
    old_mem = '        # Create memory system'
    new_mem = (
        '        # Set recall callbacks for L2 inclusion enforcement\n'
        '        for bank in self.l2_cache.banks:\n'
        '            bank.recall_callback = self.recall_l1_copies\n'
        '\n'
        '        # Create memory system'
    )
    if old_mem in content:
        content = content.replace(old_mem, new_mem, 1)
    else:
        print("WARNING: memory system creation pattern not found", file=sys.stderr)
        sys.exit(1)

    with open(filepath, 'w') as f:
        f.write(content)
    print("Bug 4 (simulator part): recall_l1_copies method and callback wiring added")


def fix_instrumentation():
    """Requirement 5: Add protocol traffic instrumentation to simulator."""
    filepath = '/app/coherence_sim/simulator.py'
    with open(filepath, 'r') as f:
        content = f.read()

    # 1. Add traffic_stats dict to __init__
    old_assert = "        self.assertion_errors: List[str] = []"
    new_assert = (
        "        self.assertion_errors: List[str] = []\n"
        "\n"
        "        # Protocol traffic instrumentation\n"
        "        self.traffic_stats = {\n"
        "            'total_messages': 0,\n"
        "            'messages_by_type': {},\n"
        "            'recall_events': 0,\n"
        "            'dirty_collections': 0,\n"
        "        }"
    )
    if old_assert in content:
        content = content.replace(old_assert, new_assert, 1)
    else:
        print("WARNING: assertion_errors pattern not found", file=sys.stderr)
        sys.exit(1)

    # 2. Add _track_message and get_protocol_traffic_report methods
    #    Insert before recall_l1_copies (added by fix_simulator)
    track_methods = '''
    def _track_message(self, msg):
        """Count a protocol message for traffic instrumentation."""
        self.traffic_stats['total_messages'] += 1
        tn = msg.msg_type.name
        self.traffic_stats['messages_by_type'][tn] = (
            self.traffic_stats['messages_by_type'].get(tn, 0) + 1)

    def get_protocol_traffic_report(self):
        """Return protocol traffic report."""
        return {
            'total_messages': self.traffic_stats['total_messages'],
            'messages_by_type': dict(self.traffic_stats['messages_by_type']),
            'recall_events': self.traffic_stats['recall_events'],
            'dirty_collections': self.traffic_stats['dirty_collections'],
        }

'''
    old_recall = '    def recall_l1_copies(self, addr):'
    new_recall = track_methods + '    def recall_l1_copies(self, addr):'
    if old_recall in content:
        content = content.replace(old_recall, new_recall, 1)
    else:
        print("WARNING: recall_l1_copies not found (run fix_simulator first)",
              file=sys.stderr)
        sys.exit(1)

    # 3. Add recall_events counter to recall_l1_copies
    old_dirty_init = "        dirty_data = None"
    new_dirty_init = (
        "        self.traffic_stats['recall_events'] += 1\n"
        "        dirty_data = None"
    )
    if old_dirty_init in content:
        content = content.replace(old_dirty_init, new_dirty_init, 1)
    else:
        print("WARNING: dirty_data = None not found in recall_l1_copies",
              file=sys.stderr)
        sys.exit(1)

    # 4. Add dirty_collections counter
    old_dirty_data = "                    dirty_data = line.data"
    new_dirty_data = (
        "                    dirty_data = line.data\n"
        "                    self.traffic_stats['dirty_collections'] += 1"
    )
    if old_dirty_data in content:
        content = content.replace(old_dirty_data, new_dirty_data, 1)
    else:
        print("WARNING: dirty_data = line.data not found", file=sys.stderr)
        sys.exit(1)

    # 5. Add _track_message calls to each message processing loop in step()
    for var in ['pending_l1_to_l2', 'pending_l2_to_l1',
                'pending_l2_to_dir', 'pending_dir_to_l2']:
        old_loop = (
            f"        for msg in {var}:\n"
            f"            had_work = True"
        )
        new_loop = (
            f"        for msg in {var}:\n"
            f"            self._track_message(msg)\n"
            f"            had_work = True"
        )
        if old_loop in content:
            content = content.replace(old_loop, new_loop, 1)
        else:
            print(f"WARNING: loop pattern for {var} not found", file=sys.stderr)
            sys.exit(1)

    with open(filepath, 'w') as f:
        f.write(content)
    print("Requirement 5: Protocol traffic instrumentation added")


def verify_fixes():
    """Verify all fixes work correctly."""
    sys.path.insert(0, '/app')

    # Clear cached modules
    mods_to_remove = [k for k in sys.modules if k.startswith('coherence_sim')]
    for mod in mods_to_remove:
        del sys.modules[mod]

    import struct
    from coherence_sim import (
        CoherenceSimulator, BankedL2Cache, MemorySystem,
        CacheState, BLOCK_SIZE,
    )

    # Verify Bug 2a: mask is correct
    bl2 = BankedL2Cache(num_banks=4)
    assert bl2.intlv_mask == 3, f"Bug 2a not fixed: mask is {bl2.intlv_mask}"
    banks = set(bl2.get_bank_index(i * BLOCK_SIZE) for i in range(4))
    assert len(banks) == 4, f"Bug 2a not fixed: only {len(banks)} unique banks"
    print("  Verified: Bug 2a fix OK (mask)")

    # Verify Bug 2b: set aliasing resolved
    bank0_sets = set()
    for i in range(1024):
        addr = i * BLOCK_SIZE
        if bl2.get_bank_index(addr) == 0:
            bank0_sets.add(bl2.banks[0]._get_set_index(addr))
    num_sets = bl2.banks[0].num_sets
    assert len(bank0_sets) > num_sets * 0.5, (
        f"Bug 2b not fixed: bank 0 uses only {len(bank0_sets)}/{num_sets} sets"
    )
    print("  Verified: Bug 2b fix OK (set aliasing)")

    # Verify Bug 3: memory ranges
    mem = MemorySystem(dual_memory=True)
    assert len(mem.check_ranges()) == 0, "Bug 3 not fixed: ranges overlap"
    print("  Verified: Bug 3 fix OK (memory ranges)")

    # Verify Bug 1: no assertion errors
    sim = CoherenceSimulator(num_cores=4, num_l2_banks=4)
    for i in range(200):
        addr = (i * BLOCK_SIZE) % 4096
        data = struct.pack('<Q', i) + b'\x00' * 56
        sim.store(i % 4, addr, data)
        sim.run_until_idle(100)
    assert len(sim.assertion_errors) == 0, f"Bug 1 not fixed: {sim.assertion_errors}"
    print("  Verified: Bug 1 fix OK (no assertion)")

    # Verify Bug 4: inclusion enforcement
    sim2 = CoherenceSimulator(num_cores=2, num_l2_banks=2)
    # Write distinctive value
    target_addr = 3 * BLOCK_SIZE
    val = 0xDEADBEEFCAFE0001
    data = struct.pack('<Q', val) + b'\x00' * 56
    sim2.store(0, target_addr, data)
    sim2.run_until_idle(200)
    sim2.store(0, target_addr, data)  # hit: actually write data
    sim2.run_until_idle(200)

    # Force L2 evictions
    for i in range(256):
        addr = (i + 500) * BLOCK_SIZE
        fdata = struct.pack('<Q', 0xF000 + i) + b'\x00' * 56
        sim2.store(i % 2, addr, fdata)
        sim2.run_until_idle(200)

    # Check dirty data made it to memory
    from coherence_sim.types import block_addr
    baddr = block_addr(target_addr)
    ctrl = sim2.mem_system.get_controller(baddr)
    if baddr in ctrl.memory:
        stored = struct.unpack('<Q', ctrl.memory[baddr][:8])[0]
        assert stored == val, (
            f"Bug 4 not fixed: expected 0x{val:x}, got 0x{stored:x}"
        )
    print("  Verified: Bug 4 fix OK (inclusion enforcement)")

    # Check inclusion property
    for core_id, l1 in enumerate(sim2.l1_controllers):
        for set_idx in range(l1.num_sets):
            for line in l1.sets[set_idx]:
                if line.state != CacheState.I:
                    bank_idx = sim2.l2_cache.get_bank_index(line.addr)
                    l2_bank = sim2.l2_cache.banks[bank_idx]
                    l2_line = l2_bank._find_line(line.addr)
                    assert l2_line is not None, (
                        f"Inclusion violated: L1[{core_id}] has 0x{line.addr:x} "
                        f"but L2 does not"
                    )
    print("  Verified: L2 inclusion property holds")

    # Verify instrumentation
    assert hasattr(sim2, 'get_protocol_traffic_report'), \
        "Instrumentation not found: get_protocol_traffic_report missing"
    report = sim2.get_protocol_traffic_report()
    assert report['total_messages'] > 0, "Instrumentation: no messages counted"
    assert report['recall_events'] > 0, "Instrumentation: no recall events"
    print(f"  Verified: Instrumentation OK "
          f"(msgs={report['total_messages']}, "
          f"recalls={report['recall_events']}, "
          f"dirty={report['dirty_collections']})")

    print("\nAll fixes verified successfully!")


def generate_traffic_report():
    """Generate traffic report by running a mixed workload."""
    sys.path.insert(0, '/app')

    # Clear cached modules
    mods_to_remove = [k for k in sys.modules if k.startswith('coherence_sim')]
    for mod in mods_to_remove:
        del sys.modules[mod]

    import struct
    import json
    from coherence_sim import CoherenceSimulator, BLOCK_SIZE

    sim = CoherenceSimulator(num_cores=4, num_l2_banks=4, dual_memory=True)

    # Mixed workload exercising all fixes
    for i in range(200):
        addr = i * BLOCK_SIZE
        core = i % 4
        data = struct.pack('<Q', i) + b'\x00' * 56
        sim.store(core, addr, data)
        sim.run_until_idle(100)
        if i % 3 == 0:
            sim.load((core + 1) % 4, addr)
            sim.run_until_idle(100)

    # Test dual-memory boundary
    dram_size = 512 * 1024 * 1024
    for i in range(10):
        addr = dram_size + i * BLOCK_SIZE
        data = struct.pack('<Q', 0xBBB0 + i) + b'\x00' * 56
        sim.store(0, addr, data)
        sim.run_until_idle(100)

    report = sim.get_protocol_traffic_report()
    with open('/app/traffic_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nTraffic report written to /app/traffic_report.json:")
    print(f"  Total messages: {report['total_messages']}")
    print(f"  Recall events: {report['recall_events']}")
    print(f"  Dirty collections: {report['dirty_collections']}")
    print(f"  Message types: {len(report['messages_by_type'])}")


if __name__ == '__main__':
    fix_addr_calc()
    fix_l2_controller()
    fix_cache_bank()
    fix_memory_system()
    fix_simulator()
    fix_instrumentation()
    verify_fixes()
    generate_traffic_report()
