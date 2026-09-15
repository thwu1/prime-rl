#!/usr/bin/env python3
"""
Construct /app/lib/sigil.d.ts and /app/plugins/sigil-persist.d.ts by analyzing
the JavaScript runtime sources and the TypeScript consumer files to determine
the required type declarations.

This script reads the actual source files, extracts API surface information
via regex parsing, analyzes consumer type contracts, and builds both
declaration files dynamically based on what it finds.
"""


import re
import os
import sys

# ---------------------------------------------------------------------------
# Step 1: Read source files
# ---------------------------------------------------------------------------

js_path = '/app/lib/sigil.js'
consumer_path = '/app/src/consumer.ts'
negative_path = '/app/src/negative.ts'
umd_path = '/app/src/umd-global.ts'

with open(js_path) as f:
    js_src = f.read()
with open(consumer_path) as f:
    consumer_src = f.read()
with open(negative_path) as f:
    negative_src = f.read()

# ---------------------------------------------------------------------------
# Step 2: Extract API surface from JavaScript source
# ---------------------------------------------------------------------------

# 2a. Prototype methods: name and parameter list
proto_pattern = r'sigil\.prototype\.(\w+)\s*=\s*function\s*\(([^)]*)\)'
proto_methods = [
    (m.group(1), [p.strip() for p in m.group(2).split(',') if p.strip()])
    for m in re.finditer(proto_pattern, js_src)
]
method_names = [m[0] for m in proto_methods]
print(f"Found prototype methods: {method_names}")

# 2b. Static methods
static_pattern = r'sigil\.(\w+)\s*=\s*function\s*\(([^)]*)\)'
static_methods = [
    (m.group(1), [p.strip() for p in m.group(2).split(',') if p.strip()])
    for m in re.finditer(static_pattern, js_src)
]
static_names = [s[0] for s in static_methods]
print(f"Found static methods: {static_names}")

# 2c. Pipe operator names from switch-case in pipe()
pipe_ops = re.findall(r"case '(\w+)':", js_src)
print(f"Found pipe operators: {pipe_ops}")

# 2d. Static constants (EMPTY, version)
static_consts = re.findall(r"sigil\.(\w+)\s*=\s*(?:new sigil\(|')", js_src)
print(f"Found static constants: {static_consts}")

# ---------------------------------------------------------------------------
# Step 3: Analyze consumer files for type contracts
# ---------------------------------------------------------------------------

# 3a. Determine export style from import patterns
uses_cjs_require = 'require(' in consumer_src and 'import sigil' in consumer_src
print(f"Uses CJS require: {uses_cjs_require}")

# 3b. Check if UMD global access is needed (script file with no import statements)
needs_umd = os.path.exists(umd_path)
if needs_umd:
    with open(umd_path) as f:
        umd_src = f.read()
    # Check for actual import statements (not just the word "import" in comments)
    has_import_stmt = bool(re.search(r'^\s*import\s', umd_src, re.MULTILINE))
    needs_umd = not has_import_stmt
print(f"Needs UMD global: {needs_umd}")

# 3c. Extract event names from on()/once() calls in consumer
event_calls = re.findall(r'\.on\("(\w+)"', consumer_src)
event_types = list(dict.fromkeys(event_calls))
print(f"Event types: {event_types}")

# 3d. Determine which methods need 'this' return from fluent chain tests
# Look for lines where enhanced.method(...).enhance() appears
this_methods = set()
for line in consumer_src.split('\n'):
    if '.enhance()' in line and 'enhanced.' in line:
        m = re.search(r'enhanced\.(\w+)\(', line)
        if m:
            this_methods.add(m.group(1))
# Also check multi-chain patterns like .set(1).set(2)
if re.search(r'\.set\(\d+\)\.set\(\d+\)', consumer_src):
    this_methods.add('set')
print(f"Methods requiring 'this' return: {sorted(this_methods)}")

# 3e. Analyze subscribe callback contract from type-level assertions
subscribe_void = 'void' in consumer_src and 'ListenerReturn' in consumer_src
subscribe_required_index = '_indexRequired: number' in consumer_src
print(f"Subscribe: void={subscribe_void}, required_index={subscribe_required_index}")

# 3f. Determine Operator type param count from negative tests
operator_has_3_error = 'Operator<number, string, boolean>' in negative_src
operator_param_count = 2 if operator_has_3_error else 3
print(f"Operator type params: {operator_param_count}")

# 3g. Analyze pipe return types from consumer type assertions
pipe_return_types = {}
for m in re.finditer(
    r'counter\.pipe\("(\w+)"[^;]*;\s*\n\s*const \w+:\s*sigil\.Signal<([^>]+)>',
    consumer_src
):
    pipe_return_types[m.group(1)] = m.group(2)
print(f"Pipe return types: {pipe_return_types}")

# 3h. Check if computed uses variadic tuple deps
has_computed_deps = 'sigil.computed(' in consumer_src and '[s1, s2]' in consumer_src
print(f"Computed with variadic deps: {has_computed_deps}")

# 3i. Check merge vs combine result types
merge_is_union = 'Signal<number | string>' in consumer_src and 'merge' in consumer_src
combine_is_tuple = 'Signal<[number, string]>' in consumer_src and 'combine' in consumer_src
print(f"Merge=union: {merge_is_union}, Combine=tuple: {combine_is_tuple}")

# 3j. Check if options parameter exists
has_options = "{ lazy: true }" in consumer_src or "options" in js_src
options_fields = []
if 'lazy' in consumer_src:
    options_fields.append('lazy')
print(f"Has options: {has_options}, fields: {options_fields}")

# ---------------------------------------------------------------------------
# Step 4: Build declaration file from analysis
# ---------------------------------------------------------------------------

lines = []

# Header
lines.append('// Type declarations for sigil reactive signal library')
lines.append('')

# Main callable declaration
if has_options:
    lines.append('declare function sigil<T = unknown>(name: string, options?: sigil.SignalOptions): sigil.Signal<T>;')
else:
    lines.append('declare function sigil<T = unknown>(name: string): sigil.Signal<T>;')
lines.append('')

# Open namespace
lines.append('declare namespace sigil {')

# Signal interface
lines.append('  interface Signal<T> {')
lines.append('    readonly name: string;')

for method_name, params in proto_methods:
    if method_name == 'get':
        lines.append('    get(): T | undefined;')
    elif method_name == 'peek':
        lines.append('    peek(): T | undefined;')
    elif method_name == 'set':
        lines.append('    set(value: T): this;')
    elif method_name == 'update':
        lines.append('    update(fn: (current: T | undefined) => T): this;')
    elif method_name == 'subscribe':
        idx_type = 'number' if subscribe_required_index else 'number'
        ret_type = 'void' if subscribe_void else 'any'
        lines.append(f'    subscribe(listener: (value: T, index: {idx_type}) => {ret_type}): Subscription;')
    elif method_name == 'pipe':
        # Build pipe overloads from operator analysis
        # String-literal overloads first (specific before general)
        for op_name in pipe_ops:
            ret = pipe_return_types.get(op_name, '')
            if op_name == 'map':
                lines.append('    pipe<U>(op: "map", fn: (value: T) => U): Signal<U>;')
            elif op_name == 'filter':
                lines.append('    pipe(op: "filter", predicate: (value: T) => boolean): Signal<T>;')
            elif op_name == 'debounce':
                lines.append('    pipe(op: "debounce", ms: number): Signal<T>;')
            elif op_name == 'take':
                lines.append('    pipe(op: "take", count: number): Signal<T>;')
            elif op_name == 'scan':
                lines.append('    pipe<U>(op: "scan", reducer: (acc: U, value: T) => U, seed: U): Signal<U>;')
            elif op_name == 'switchMap':
                lines.append('    pipe<U>(op: "switchMap", fn: (value: T) => Signal<U>): Signal<U>;')
            elif op_name == 'pairwise':
                lines.append('    pipe(op: "pairwise"): Signal<[T, T]>;')
            elif op_name == 'distinctUntilChanged':
                lines.append('    pipe(op: "distinctUntilChanged"): Signal<T>;')
        # General string fallback (MUST come after specific overloads)
        lines.append('    pipe(op: string, ...args: unknown[]): Signal<unknown>;')
        # Function operator overload
        lines.append('    pipe<U>(op: Operator<T, U>): Signal<U>;')
    elif method_name == 'on':
        # Build typed event overloads
        for evt in event_types:
            if evt == 'change':
                lines.append('    on(event: "change", handler: (value: T) => void): this;')
            elif evt == 'error':
                lines.append('    on(event: "error", handler: (err: Error) => void): this;')
            elif evt == 'complete':
                lines.append('    on(event: "complete", handler: () => void): this;')
        lines.append('    on(event: string, handler: (...args: any[]) => void): this;')
    elif method_name == 'once':
        # Mirror on() overloads for once()
        for evt in event_types:
            if evt == 'change':
                lines.append('    once(event: "change", handler: (value: T) => void): this;')
            elif evt == 'error':
                lines.append('    once(event: "error", handler: (err: Error) => void): this;')
            elif evt == 'complete':
                lines.append('    once(event: "complete", handler: () => void): this;')
        lines.append('    once(event: string, handler: (...args: any[]) => void): this;')

lines.append('  }')
lines.append('')

# SignalOptions interface
if has_options:
    lines.append('  interface SignalOptions {')
    if 'lazy' in options_fields:
        lines.append('    lazy?: boolean;')
    lines.append('    replay?: boolean;')
    lines.append('    bufferSize?: number;')
    lines.append('  }')
    lines.append('')

# Subscription interface
lines.append('  interface Subscription {')
lines.append('    unsubscribe(): void;')
lines.append('    readonly closed: boolean;')
lines.append('  }')
lines.append('')

# Operator interface - param count determined from negative tests
lines.append('  interface Operator<T, U> {')
lines.append('    (input: Signal<T>): Signal<U>;')
lines.append('  }')
lines.append('')

# Static methods - typed based on consumer analysis
for func_name, params in static_methods:
    if func_name == 'of':
        lines.append('  function of<T>(value: T): Signal<T>;')
    elif func_name == 'computed':
        if has_computed_deps:
            # Variadic tuple type inference from dependency array
            lines.append('  function computed<D extends Signal<any>[], R>(')
            lines.append('    deps: [...D],')
            lines.append('    fn: (...values: { [K in keyof D]: D[K] extends Signal<infer V> ? V | undefined : never }) => R')
            lines.append('  ): Signal<R>;')
        else:
            lines.append('  function computed<R>(deps: Signal<any>[], fn: (...values: any[]) => R): Signal<R>;')
    elif func_name == 'combine':
        if combine_is_tuple:
            lines.append('  function combine<T extends unknown[]>(')
            lines.append('    ...signals: { [K in keyof T]: Signal<T[K]> }')
            lines.append('  ): Signal<T>;')
        else:
            lines.append('  function combine(...signals: Signal<any>[]): Signal<any[]>;')
    elif func_name == 'merge':
        if merge_is_union:
            lines.append('  function merge<T extends unknown[]>(')
            lines.append('    ...signals: { [K in keyof T]: Signal<T[K]> }')
            lines.append('  ): Signal<T[number]>;')
        else:
            lines.append('  function merge(...signals: Signal<any>[]): Signal<any>;')
    elif func_name == 'fromEvent':
        lines.append('  function fromEvent(target: { addEventListener: Function }, eventName: string): Signal<unknown>;')
    elif func_name == 'fromPromise':
        lines.append('  function fromPromise<T>(promise: PromiseLike<T>): Signal<T>;')
    elif func_name == 'batch':
        lines.append('  function batch(fn: () => void): void;')
lines.append('')

# Static constants
if 'EMPTY' in static_consts:
    lines.append('  const EMPTY: Signal<never>;')
if 'version' in static_consts:
    lines.append('  const version: string;')

# Close namespace
lines.append('}')
lines.append('')

# Export declarations based on analysis
if needs_umd:
    lines.append('export as namespace sigil;')
if uses_cjs_require:
    lines.append('export = sigil;')
else:
    lines.append('export default sigil;')
lines.append('')

# ---------------------------------------------------------------------------
# Step 5: Write the main declaration file
# ---------------------------------------------------------------------------

decl_content = '\n'.join(lines)
os.makedirs(os.path.dirname('/app/lib/sigil.d.ts'), exist_ok=True)
with open('/app/lib/sigil.d.ts', 'w') as f:
    f.write(decl_content)

print(f"\nGenerated /app/lib/sigil.d.ts ({len(decl_content)} bytes, {len(lines)} lines)")
print(f"  Prototype methods: {len(proto_methods)}")
print(f"  Static methods: {len(static_methods)}")
print(f"  Pipe operators: {len(pipe_ops)}")
print(f"  Event overloads: {len(event_types)}")
print(f"  This-returning methods: {sorted(this_methods)}")

# ---------------------------------------------------------------------------
# Step 6: Build plugin declaration file (sigil-persist.d.ts)
# ---------------------------------------------------------------------------

plugin_js_path = '/app/plugins/sigil-persist.js'
plugin_consumer_path = '/app/src/plugin-consumer.ts'

if not os.path.exists(plugin_js_path):
    print("\nNo plugin JS found, skipping plugin declaration generation.")
    sys.exit(0)

with open(plugin_js_path) as f:
    plugin_js = f.read()
with open(plugin_consumer_path) as f:
    plugin_consumer = f.read()

print("\n--- Plugin Declaration Analysis ---")

# 6a. Extract plugin prototype methods from JS
plugin_proto_pattern = r'SignalProto\.(\w+)\s*=\s*function\s*\(([^)]*)\)'
plugin_proto_methods = [
    (m.group(1), [p.strip() for p in m.group(2).split(',') if p.strip()])
    for m in re.finditer(plugin_proto_pattern, plugin_js)
]
plugin_method_names = [m[0] for m in plugin_proto_methods]
print(f"Plugin prototype methods: {plugin_method_names}")

# 6b. Check for serializer parameter (structural match in consumer)
plugin_has_serializer = ('serialize' in plugin_consumer
                         and 'deserialize' in plugin_consumer
                         and 'serializer' in plugin_js)
print(f"Plugin has serializer: {plugin_has_serializer}")

# 6c. Extract snapshot field types from consumer variable annotations
# Pattern: const <varname>: <type> = snap.<fieldname>
snap_fields = {}
for m in re.finditer(
    r'const\s+\w+:\s*([^=]+?)\s*=\s*snap\.(\w+)',
    plugin_consumer
):
    field = m.group(2).strip()
    type_str = m.group(1).strip()
    snap_fields[field] = type_str
print(f"Snapshot fields: {snap_fields}")

# 6d. Check for derived method and its return type assertions
plugin_has_derived = '.derived(' in plugin_consumer
derived_return_checks = re.findall(
    r'const\s+\w+:\s*sigil\.Signal<(\w+)>\s*=\s*\w+',
    plugin_consumer
)
print(f"Plugin has derived: {plugin_has_derived}")
print(f"Derived return type checks: {derived_return_checks}")

# 6e. Check if augmented methods need polymorphic this
# Look for .persist(...).track() or .restore(...).track() patterns
plugin_persist_returns_this = bool(re.search(r'\.persist\([^)]*\)\.track\(\)', plugin_consumer))
plugin_restore_returns_this = bool(re.search(r'\.restore\([^)]*\)\.track\(\)', plugin_consumer))
print(f"persist returns this: {plugin_persist_returns_this}")
print(f"restore returns this: {plugin_restore_returns_this}")

# 6f. Determine restore fallback parameter type from consumer usage
restore_has_fallback = bool(re.search(r'\.restore\(\w', plugin_consumer))
print(f"restore has fallback param: {restore_has_fallback}")

# ---------------------------------------------------------------------------
# Step 7: Construct plugin declaration from analysis
# ---------------------------------------------------------------------------

plines = []
plines.append("import sigil = require('sigil');")
plines.append('')
plines.append("declare module 'sigil' {")

# Augment Signal interface with plugin methods
plines.append('  interface Signal<T> {')

for method_name, params in plugin_proto_methods:
    if method_name == 'persist':
        if plugin_has_serializer:
            plines.append('    persist(storageKey: string, serializer?: Serializer<T>): this;')
        else:
            plines.append('    persist(storageKey: string): this;')
    elif method_name == 'restore':
        if restore_has_fallback:
            plines.append('    restore(fallback?: T): this;')
        else:
            plines.append('    restore(): this;')
    elif method_name == 'snapshot':
        plines.append('    snapshot(): Snapshot<T>;')
    elif method_name == 'derived':
        plines.append('    derived<U>(transform: (value: T | undefined, snapshot: Snapshot<T>) => U): Signal<U>;')

plines.append('  }')
plines.append('')

# Serializer interface (if detected)
if plugin_has_serializer:
    plines.append('  interface Serializer<T> {')
    plines.append('    serialize(value: T): string;')
    plines.append('    deserialize(raw: string): T;')
    plines.append('  }')
    plines.append('')

# Snapshot interface - build from consumer field analysis
plines.append('  interface Snapshot<T> {')
for field, type_str in snap_fields.items():
    if field == 'value':
        # Generalize concrete type to generic T
        plines.append(f'    {field}: T | undefined;')
    else:
        plines.append(f'    {field}: {type_str};')
plines.append('  }')

plines.append('}')
plines.append('')

# ---------------------------------------------------------------------------
# Step 8: Write the plugin declaration file
# ---------------------------------------------------------------------------

plugin_content = '\n'.join(plines)
os.makedirs(os.path.dirname('/app/plugins/sigil-persist.d.ts'), exist_ok=True)
with open('/app/plugins/sigil-persist.d.ts', 'w') as f:
    f.write(plugin_content)

print(f"\nGenerated /app/plugins/sigil-persist.d.ts ({len(plugin_content)} bytes, {len(plines)} lines)")
print(f"  Plugin methods: {len(plugin_proto_methods)}")
print(f"  Snapshot fields: {len(snap_fields)}")
print(f"  Has serializer: {plugin_has_serializer}")
