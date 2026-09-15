#!/bin/bash

# Deploy the reimplementation
cp /solution/graphtool_impl.py /app/graphtool.py

# Verify correctness against the reference binary on diverse inputs
python3 -c "
import subprocess, tempfile, os, sys

def check(graph, args, label, binary=False):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.grph', delete=False) as f:
        f.write(graph)
        tmp = f.name
    try:
        cmd_ref = ['/app/ref_tool', args[0], tmp] + args[1:]
        cmd_imp = ['python3', '/app/graphtool.py', args[0], tmp] + args[1:]
        if binary:
            ref = subprocess.run(cmd_ref, capture_output=True, timeout=10)
            imp = subprocess.run(cmd_imp, capture_output=True, timeout=10)
            if ref.stdout != imp.stdout or ref.returncode != imp.returncode:
                print(f'FAIL: {label} (binary mismatch, ref={len(ref.stdout)}B, imp={len(imp.stdout)}B)', file=sys.stderr)
                sys.exit(1)
        else:
            ref = subprocess.run(cmd_ref, capture_output=True, text=True, timeout=10)
            imp = subprocess.run(cmd_imp, capture_output=True, text=True, timeout=10)
            if ref.stdout != imp.stdout or ref.returncode != imp.returncode:
                print(f'FAIL: {label}', file=sys.stderr)
                print(f'  ref stdout: {ref.stdout!r}', file=sys.stderr)
                print(f'  imp stdout: {imp.stdout!r}', file=sys.stderr)
                print(f'  ref rc: {ref.returncode}, imp rc: {imp.returncode}', file=sys.stderr)
                sys.exit(1)
    finally:
        os.unlink(tmp)

dag = 'node A\nnode B\nnode C\nedge A -> B\nedge B -> C\nedge A -> C\n'
weighted = '@weighted\nedge A -> B 1.0\nedge A -> C 5.0\nedge B -> C 2.0\nedge B -> D 4.0\nedge C -> D 1.0\n'
cyclic = 'edge A -> B\nedge B -> C\nedge C -> A\n'
selfloop = 'edge A -> B\nedge A -> B\nedge A -> A\nedge B -> A\n'

# Test original commands
for g, name in [(dag, 'dag'), (weighted, 'weighted'), (cyclic, 'cyclic'), (selfloop, 'selfloop')]:
    check(g, ['info'], f'{name}/info')
    check(g, ['adj'], f'{name}/adj')
    check(g, ['topo'], f'{name}/topo')

check(dag, ['shortest', 'A', 'C'], 'dag/shortest')
check(dag, ['allpaths', 'A', 'C'], 'dag/allpaths')
check(weighted, ['shortest', 'A', 'D'], 'weighted/shortest')
check(weighted, ['allpaths', 'A', 'D'], 'weighted/allpaths')
check(cyclic, ['allpaths', 'A', 'C'], 'cyclic/allpaths')

# Test new commands
for g, name in [(dag, 'dag'), (weighted, 'weighted'), (cyclic, 'cyclic')]:
    check(g, ['serialize'], f'{name}/serialize', binary=True)
    check(g, ['pagerank'], f'{name}/pagerank')
    check(g, ['scc'], f'{name}/scc')

check(dag, ['pagerank', '0.9', '50'], 'dag/pagerank-custom')

# Test serialize/deserialize round-trip
import struct, zlib
ref_bin = subprocess.run(['/app/ref_tool', 'serialize', '/dev/stdin'],
    input=dag.encode(), capture_output=True, timeout=10)
# Actually use temp file approach
with tempfile.NamedTemporaryFile(mode='w', suffix='.grph', delete=False) as f:
    f.write(dag)
    tmp_txt = f.name
ref_ser = subprocess.run(['/app/ref_tool', 'serialize', tmp_txt], capture_output=True, timeout=10)
os.unlink(tmp_txt)
with tempfile.NamedTemporaryFile(suffix='.grb', delete=False) as f:
    f.write(ref_ser.stdout)
    tmp_bin = f.name
ref_deser = subprocess.run(['/app/ref_tool', 'deserialize', tmp_bin], capture_output=True, text=True, timeout=10)
imp_deser = subprocess.run(['python3', '/app/graphtool.py', 'deserialize', tmp_bin], capture_output=True, text=True, timeout=10)
os.unlink(tmp_bin)
if ref_deser.stdout != imp_deser.stdout:
    print(f'FAIL: deserialize round-trip', file=sys.stderr)
    sys.exit(1)

print('All verification checks passed')
"
