#!/usr/bin/env python3

"""Fix all bugs in the PipeWeave framework.

Bug 1 (config.py):     Variable interpolation regex too restrictive.
Bug 2 (engine.py):     Post-hooks execute FIFO instead of LIFO.
Bug 3 (transforms.py): Outer-join drops right-only fields.
Bug 4 (formatter.py):  ANSI regex misses multi-parameter codes.
Bug 5 (schema.py):     Optional-field defaults never applied.
"""

# --- Bug 1: config.py ---------------------------------------------------
with open('/app/pipeweave/config.py', 'r') as f:
    src = f.read()
src = src.replace(
    r"_VAR_PATTERN = re.compile(r'\$\{([a-zA-Z_]+)\}')",
    r"_VAR_PATTERN = re.compile(r'\$\{([a-zA-Z_][a-zA-Z0-9_.]*)\}')",
)
with open('/app/pipeweave/config.py', 'w') as f:
    f.write(src)
print('[fix] config.py: variable interpolation regex widened')

# --- Bug 2: engine.py ---------------------------------------------------
with open('/app/pipeweave/engine.py', 'r') as f:
    src = f.read()
src = src.replace(
    'self.post_hooks.append(hook_fn)',
    'self.post_hooks.appendleft(hook_fn)',
)
with open('/app/pipeweave/engine.py', 'w') as f:
    f.write(src)
print('[fix] engine.py: post-hook registration → appendleft (LIFO)')

# --- Bug 3: transforms.py -----------------------------------------------
with open('/app/pipeweave/transforms.py', 'r') as f:
    src = f.read()

old_block = """\
    if how == 'outer':
        for i, record in enumerate(right):
            if i not in right_matched:
                padded = {}
                for field in left_fields:
                    padded[field] = None
                for field in left_fields:
                    if field in record:
                        padded[field] = record[field]
                result.append(padded)"""

new_block = """\
    if how == 'outer':
        for i, record in enumerate(right):
            if i not in right_matched:
                padded = {}
                for field in left_fields:
                    padded[field] = None
                padded.update(record)
                result.append(padded)"""

src = src.replace(old_block, new_block)
with open('/app/pipeweave/transforms.py', 'w') as f:
    f.write(src)
print('[fix] transforms.py: outer-join preserves right-only fields')

# --- Bug 4: formatter.py ------------------------------------------------
with open('/app/pipeweave/formatter.py', 'r') as f:
    src = f.read()
src = src.replace(
    r"_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9]+m')",
    r"_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')",
)
with open('/app/pipeweave/formatter.py', 'w') as f:
    f.write(src)
print('[fix] formatter.py: ANSI regex handles multi-parameter codes')

# --- Bug 5: schema.py ---------------------------------------------------
with open('/app/pipeweave/schema.py', 'r') as f:
    src = f.read()
src = src.replace(
    "                elif 'default' in spec:\n                    continue",
    "                elif 'default' in spec:\n                    result[field_name] = spec['default']\n                    continue",
    1,
)
with open('/app/pipeweave/schema.py', 'w') as f:
    f.write(src)
print('[fix] schema.py: optional-field defaults now applied')

print('\nAll bugs fixed.')
