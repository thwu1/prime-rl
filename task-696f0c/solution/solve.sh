#!/bin/bash


set -e

# --- Build CaDiCaL SAT solver from release tarball ---
cd /tmp
wget -q https://github.com/arminbiere/cadical/archive/refs/tags/rel-2.0.0.tar.gz -O cadical.tar.gz

python3 -c "
import tarfile
with tarfile.open('/tmp/cadical.tar.gz') as t:
    for m in t.getmembers():
        t.extract(m, '/tmp', set_attrs=False)
"

find /tmp/cadical-rel-2.0.0 -name 'configure' -exec chmod +x {} +
find /tmp/cadical-rel-2.0.0 -name '*.sh' -exec chmod +x {} +

cd /tmp/cadical-rel-2.0.0
./configure && make -j"$(nproc)"
cp build/cadical /usr/local/bin/cadical

# --- Build drat-trim proof checker ---
wget -q https://raw.githubusercontent.com/marijnheule/drat-trim/master/drat-trim.c -O /tmp/drat-trim.c || \
wget -q https://raw.githubusercontent.com/marijnheule/drat-trim/main/drat-trim.c -O /tmp/drat-trim.c
gcc -O2 -o /usr/local/bin/drat-trim /tmp/drat-trim.c

# --- Run the chromatic number certification pipeline ---
cd /app
python3 /solution/solve_graphs.py
