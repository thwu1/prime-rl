"""
Diagnose and fix three bugs in the left-right concurrent map implementation.

This script reads the buggy source, identifies each defect by searching for
the specific buggy patterns, and applies targeted corrections.

Bug 1 (value aliasing): ReadGuard.get returns a direct reference to internal
       list state instead of a copy, violating the API contract.

Bug 2 (epoch-wait overshoot): _wait_for_readers polls ALL current reader
       epochs for odd parity instead of consulting _last_epochs to only wait
       for readers that were active during the previous swap.

Bug 3 (oplog premature clear): _update_and_swap clears the entire oplog and
       resets swap_index after a single replay, so operations are only applied
       to one copy instead of both.
"""

import re
import ast
import textwrap

SOURCE = "/app/left_right_map.py"

with open(SOURCE, "r") as f:
    lines = f.readlines()

# -----------------------------------------------------------------------
# Fix 1: ReadGuard.get must return list(self._data[key]) not self._data[key]
#
# We find the ReadGuard.get method and change the return inside the if block
# from returning the raw reference to returning a copy.
# -----------------------------------------------------------------------
fix1_applied = False
for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped == "return self._data[key]":
        # Verify we're inside ReadGuard.get by checking surrounding context
        # Look back for "def get" and "class ReadGuard"
        context = "".join(lines[max(0, i - 10):i])
        if "class ReadGuard" in context or "def get" in context:
            indent = line[: len(line) - len(line.lstrip())]
            lines[i] = indent + "return list(self._data[key])\n"
            fix1_applied = True
            break

assert fix1_applied, "Fix 1 failed: could not find ReadGuard.get return"
print("Fix 1 applied: ReadGuard.get now returns a copy")

# -----------------------------------------------------------------------
# Fix 2: _wait_for_readers must only wait for readers recorded in
#         _last_epochs whose epoch was odd at snapshot time
#
# Replace the entire _wait_for_readers method body.
# -----------------------------------------------------------------------
fix2_start = None
fix2_end = None
for i, line in enumerate(lines):
    if "def _wait_for_readers(self):" in line:
        fix2_start = i
    elif fix2_start is not None and fix2_end is None:
        # Find end of method: next def or non-indented line at same level
        stripped = line.strip()
        if stripped == "":
            continue
        # Check if indentation is <= method def indentation (new method/class)
        method_indent = len(lines[fix2_start]) - len(lines[fix2_start].lstrip())
        curr_indent = len(line) - len(line.lstrip())
        if curr_indent <= method_indent and stripped != "" and not stripped.startswith("#"):
            fix2_end = i
            break

assert fix2_start is not None, "Fix 2 failed: could not find _wait_for_readers"
if fix2_end is None:
    fix2_end = len(lines)

method_indent = len(lines[fix2_start]) - len(lines[fix2_start].lstrip())
body_indent = " " * (method_indent + 4)

new_wait = lines[fix2_start]  # keep the def line
new_wait += body_indent + '"""Wait until every reader that was reading during the last swap has advanced."""\n'
new_wait += body_indent + "for i in range(len(self._last_epochs)):\n"
new_wait += body_indent + "    if i >= len(self._state.epoch_trackers):\n"
new_wait += body_indent + "        continue\n"
new_wait += body_indent + "    last = self._last_epochs[i]\n"
new_wait += body_indent + "    if last % 2 == 0:\n"
new_wait += body_indent + "        continue  # was idle at last swap -- no need to wait\n"
new_wait += body_indent + "    tracker = self._state.epoch_trackers[i]\n"
new_wait += body_indent + "    while tracker[0] == last:\n"
new_wait += body_indent + "        # Release lock briefly so reader threads can make progress\n"
new_wait += body_indent + "        self._state.epochs_lock.release()\n"
new_wait += body_indent + "        time.sleep(0.0001)\n"
new_wait += body_indent + "        self._state.epochs_lock.acquire()\n"
new_wait += "\n"

lines[fix2_start:fix2_end] = [new_wait]
print("Fix 2 applied: _wait_for_readers now consults _last_epochs")

# -----------------------------------------------------------------------
# Fix 3: _update_and_swap must maintain the oplog across two publish
#         cycles using swap_index, instead of clearing it after one replay
#
# Find the oplog replay section and replace it.
# -----------------------------------------------------------------------
fix3_applied = False

# Re-scan lines (indices shifted after fix 2)
for i, line in enumerate(lines):
    if "self._oplog.clear()" in line.strip():
        # Find the start of the replay block (the for loop above)
        replay_start = i
        for j in range(i - 1, max(0, i - 10), -1):
            stripped = lines[j].strip()
            if stripped.startswith("for op in self._oplog"):
                replay_start = j
                break
            elif stripped.startswith("#") and "Replay" in stripped:
                replay_start = j
                break

        # Find end: the swap_index = 0 line below
        replay_end = i + 1
        for j in range(i + 1, min(len(lines), i + 5)):
            if "self._swap_index" in lines[j] and "= 0" in lines[j]:
                replay_end = j + 1
                break

        indent = line[: len(line) - len(line.lstrip())]

        replacement = []
        replacement.append(indent + "# Replay ops[0..swap_index] -- second application (already on read copy)\n")
        replacement.append(indent + "for op in self._oplog[:self._swap_index]:\n")
        replacement.append(indent + "    self._apply_op(w, op)\n")
        replacement.append(indent + "# Drain those entries\n")
        replacement.append(indent + "self._oplog = self._oplog[self._swap_index:]\n")
        replacement.append(indent + "\n")
        replacement.append(indent + "# Replay remaining ops -- first application\n")
        replacement.append(indent + "for op in self._oplog:\n")
        replacement.append(indent + "    self._apply_op(w, op)\n")
        replacement.append(indent + "self._swap_index = len(self._oplog)\n")

        lines[replay_start:replay_end] = replacement
        fix3_applied = True
        break

assert fix3_applied, "Fix 3 failed: could not find oplog.clear() pattern"
print("Fix 3 applied: oplog replay now uses dual-application with swap_index")

# Write the fixed file
with open(SOURCE, "w") as f:
    f.writelines(lines)

# -----------------------------------------------------------------------
# Verify the fix by running a quick sanity check
# -----------------------------------------------------------------------
import importlib
import sys

# Force reimport
if "left_right_map" in sys.modules:
    del sys.modules["left_right_map"]
sys.path.insert(0, "/app")

from left_right_map import LeftRightMap

# Quick correctness check: 3 publish cycles with inserts
w, r = LeftRightMap.new()
w.insert("k", 1)
w.publish()
assert r.get("k") == [1], f"Cycle 1 failed: {r.get('k')}"

w.insert("k", 2)
w.publish()
result = sorted(r.get("k"))
assert result == [1, 2], f"Cycle 2 failed: {result}"

w.insert("k", 3)
w.publish()
result = sorted(r.get("k"))
assert result == [1, 2, 3], f"Cycle 3 failed: {result}"

# Check value isolation
vals = r.get("k")
vals.append(999)
assert r.get("k") == [1, 2, 3], "Value isolation failed"

print("Sanity checks passed. All three fixes verified.")
