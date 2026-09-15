#!/usr/bin/env python3
"""
Fix all bugs in the cache eviction system and run benchmark.

"""

import subprocess

# --- Fix 1: Clock wrap in engine.py idle_time() ---
with open('/app/engine.py', 'r') as f:
    code = f.read()

code = code.replace(
    '            return current + self.access_clock',
    '            return (CLOCK_MAX - self.access_clock) + current + 1'
)

with open('/app/engine.py', 'w') as f:
    f.write(code)

print("Fixed: clock wrap in idle_time()")


# --- Fix 2, 3, 4: Policies bugs ---
with open('/app/policies.py', 'r') as f:
    code = f.read()

# Fix 2: Logarithmic frequency increment (was linear)
code = code.replace(
    '''    def on_hit(self, entry):
        """Update frequency on cache hit."""
        entry.frequency += 1''',
    '''    def on_hit(self, entry):
        """Update frequency on cache hit (logarithmic increment)."""
        counter = entry.frequency
        if counter >= 255:
            return
        baseval = max(0, counter - FREQ_INIT_VAL)
        p = 1.0 / (baseval * self.log_factor + 1)
        if self.engine.rng.random() < p:
            entry.frequency = counter + 1'''
)

# Fix 3: Decay handles clock wrap correctly
code = code.replace(
    '''    def _decayed_frequency(self, entry):
        """Get frequency after applying time-based decay."""
        current = self.engine.clock & CLOCK_MAX
        last = entry.last_decay_clock
        elapsed = current - last
        if elapsed < 0:
            elapsed = 0''',
    '''    def _decayed_frequency(self, entry):
        """Get frequency after applying time-based decay."""
        current = self.engine.clock & CLOCK_MAX
        last = entry.last_decay_clock
        if current >= last:
            elapsed = current - last
        else:
            elapsed = (CLOCK_MAX - last) + current + 1'''
)

# Fix 4: Pool stale entry retry loop
code = code.replace(
    '''        # Try the best candidate from the pool
        victim = self.pool.pop_best()
        if victim is not None and victim in self.engine.store:
            return victim

        # Fallback: highest score from current sample''',
    '''        # Try candidates from pool, skipping stale entries
        while len(self.pool) > 0:
            victim = self.pool.pop_best()
            if victim is not None and victim in self.engine.store:
                return victim

        # Fallback: highest score from current sample'''
)

with open('/app/policies.py', 'w') as f:
    f.write(code)

print("Fixed: logarithmic frequency, clock-aware decay, pool retry")


# --- Fix 5: Non-deterministic workload generator ---
with open('/app/workloads.py', 'r') as f:
    code = f.read()

code = code.replace(
    '        if random.random() < 0.8:',
    '        if rng.random() < 0.8:'
)

with open('/app/workloads.py', 'w') as f:
    f.write(code)

print("Fixed: temporal_locality_workload determinism")


# --- Run benchmark ---
print("\nRunning benchmark...")
subprocess.run(['python3', '/app/benchmark.py'], check=True)
print("Done!")
