"""Fix the online softmax m_i update order bug in engine.py.

The bug: m_i = m_ij appears immediately after m_ij = np.maximum(m_i, row_max),
BEFORE the alpha computation. Since m_i and m_ij are now equal, alpha is always 1,
meaning the old accumulator is never rescaled when a new K tile has a larger max.

The fix: move m_i = m_ij to after acc += p @ v_tile.
"""
import re

with open('/app/engine.py', 'r') as f:
    lines = f.readlines()

# Find the pattern: m_i = m_ij appearing before the errstate block
# and move it to after acc += p @ v_tile
output_lines = []
skip_mi_update = False
insert_after_acc = False

for i, line in enumerate(lines):
    stripped = line.strip()

    # Detect the premature m_i = m_ij (appears right after m_ij = ...)
    if stripped == '# Update running max' and i + 1 < len(lines):
        # Skip this comment and the next line (m_i = m_ij)
        skip_mi_update = True
        continue

    if skip_mi_update and stripped == 'm_i = m_ij':
        skip_mi_update = False
        continue

    skip_mi_update = False

    output_lines.append(line)

    # Insert m_i = m_ij after "acc += p @ v_tile"
    if stripped == 'acc += p @ v_tile':
        # Get the indentation from the current line
        indent = line[:len(line) - len(line.lstrip())]
        output_lines.append(indent + 'm_i = m_ij\n')

with open('/app/engine.py', 'w') as f:
    f.writelines(output_lines)

# Verify the fix by checking the file
with open('/app/engine.py', 'r') as f:
    content = f.read()

# Verify m_i = m_ij now appears after acc update
acc_pos = content.find('acc += p @ v_tile')
mi_pos = content.find('m_i = m_ij', acc_pos)
alpha_pos = content.find('alpha = np.nan_to_num')

assert mi_pos > acc_pos, "m_i = m_ij should be after acc += p @ v_tile"
assert mi_pos > alpha_pos, "m_i = m_ij should be after alpha computation"

print("Fixed engine.py: moved m_i update to after accumulator updates")
