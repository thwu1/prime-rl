#!/usr/bin/env python3
"""
Fix the 4 bugs in /app/mars.py:
1. SPL process queue ordering (must queue PC+1 before A-target)
2. CMP.I/SNE.I must compare full instruction (opcode, modifier, modes)
3. B-operand post-increment timing (must resolve address before incrementing)
4. DIV/MOD .F/.X partial zero (non-zero component must still execute)
"""
import re

with open("/app/mars.py", "r") as f:
    src = f.read()

# ====================================================================
# Bug 1: SPL queues A-target before PC+1 (should be PC+1 first)
# ====================================================================
src = src.replace(
    "        elif ir_op == SPL:\n"
    "            if len(queue) < self.max_processes:\n"
    "                queue.append(addrA)\n"
    "            queue.append((pc + 1) % M)",

    "        elif ir_op == SPL:\n"
    "            queue.append((pc + 1) % M)\n"
    "            if len(queue) < self.max_processes:\n"
    "                queue.append(addrA)"
)

# ====================================================================
# Bug 2: CMP.I only compares values, not full instruction structure
# ====================================================================
src = src.replace(
    "            elif ir_mod == mI:\n"
    "                eq = (aa_val == ab_val and ira_bval == irb_bval)\n"
    "            else:\n"
    "                eq = False\n"
    "            queue.append((pc + 2) % M if eq else (pc + 1) % M)",

    "            elif ir_mod == mI:\n"
    "                ca = core[addrA]\n"
    "                cb = core[addrB]\n"
    "                eq = (ca.op == cb.op and ca.mod == cb.mod and\n"
    "                      ca.am == cb.am and ca.bm == cb.bm and\n"
    "                      aa_val == ab_val and ira_bval == irb_bval)\n"
    "            else:\n"
    "                eq = False\n"
    "            queue.append((pc + 2) % M if eq else (pc + 1) % M)"
)

# SNE.I same bug
src = src.replace(
    "            elif ir_mod == mI:\n"
    "                ne = not (aa_val == ab_val and ira_bval == irb_bval)",

    "            elif ir_mod == mI:\n"
    "                ca = core[addrA]\n"
    "                cb = core[addrB]\n"
    "                ne = not (ca.op == cb.op and ca.mod == cb.mod and\n"
    "                          ca.am == cb.am and ca.bm == cb.bm and\n"
    "                          aa_val == ab_val and ira_bval == irb_bval)"
)

# ====================================================================
# Bug 3: B-operand post-increment happens before address resolution
# ====================================================================
# Find the B-operand section and fix the ordering
old_b_postinc = (
    "            if base_mode == POSTINC:\n"
    "                temp_b = (temp_b + 1) % M\n"
    "                if use_a_field:\n"
    "                    inter_cell.an = temp_b\n"
    "                else:\n"
    "                    inter_cell.bn = temp_b\n"
    "\n"
    "            addrB = (inter_b + temp_b) % M\n"
    "            c = core[addrB]\n"
    "            ab_val = c.an\n"
    "            irb_bval = c.bn"
)
new_b_postinc = (
    "            addrB = (inter_b + temp_b) % M\n"
    "            c = core[addrB]\n"
    "            ab_val = c.an\n"
    "            irb_bval = c.bn\n"
    "\n"
    "            if base_mode == POSTINC:\n"
    "                temp_b = (temp_b + 1) % M\n"
    "                if use_a_field:\n"
    "                    inter_cell.an = temp_b\n"
    "                else:\n"
    "                    inter_cell.bn = temp_b"
)
src = src.replace(old_b_postinc, new_b_postinc)

# ====================================================================
# Bug 4: DIV/MOD .F/.I and .X skip both components on any zero divisor
# ====================================================================
old_div_f = (
    "            elif ir_mod in (mF, mI):\n"
    "                ra = dm(aa_val, ab_val)\n"
    "                rb = dm(ira_bval, irb_bval)\n"
    "                if ra is None or rb is None:\n"
    "                    died = True\n"
    "                else:\n"
    "                    target.an = ra\n"
    "                    target.bn = rb\n"
    "            elif ir_mod == mX:\n"
    "                ra = dm(ira_bval, ab_val)\n"
    "                rb = dm(aa_val, irb_bval)\n"
    "                if ra is None or rb is None:\n"
    "                    died = True\n"
    "                else:\n"
    "                    target.an = ra\n"
    "                    target.bn = rb"
)
new_div_f = (
    "            elif ir_mod in (mF, mI):\n"
    "                ra = dm(aa_val, ab_val)\n"
    "                rb = dm(ira_bval, irb_bval)\n"
    "                if ra is not None:\n"
    "                    target.an = ra\n"
    "                    if rb is not None:\n"
    "                        target.bn = rb\n"
    "                    else:\n"
    "                        died = True\n"
    "                else:\n"
    "                    if rb is not None:\n"
    "                        target.bn = rb\n"
    "                    died = True\n"
    "            elif ir_mod == mX:\n"
    "                ra = dm(ira_bval, ab_val)\n"
    "                rb = dm(aa_val, irb_bval)\n"
    "                if ra is not None:\n"
    "                    target.an = ra\n"
    "                    if rb is not None:\n"
    "                        target.bn = rb\n"
    "                    else:\n"
    "                        died = True\n"
    "                else:\n"
    "                    if rb is not None:\n"
    "                        target.bn = rb\n"
    "                    died = True"
)
src = src.replace(old_div_f, new_div_f)

with open("/app/mars.py", "w") as f:
    f.write(src)

print("All 4 bugs fixed in /app/mars.py")
