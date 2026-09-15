"""Fix the ConcurrentProgram.java lock scanning bug."""

import re

path = '/app/src/modelchecker/ConcurrentProgram.java'
with open(path, 'r') as f:
    content = f.read()

# The bug: only threads.get(0) is scanned for lock names.
# Fix: iterate all threads to discover all locks.
old_block = """        Set<String> lockSet = new LinkedHashSet<>();
        for (Statement s : threads.get(0)) {
            String l = s.getAccessedLock();
            if (l != null) lockSet.add(l);
        }"""

new_block = """        Set<String> lockSet = new LinkedHashSet<>();
        for (List<Statement> prog : threads) {
            for (Statement s : prog) {
                String l = s.getAccessedLock();
                if (l != null) lockSet.add(l);
            }
        }"""

if old_block in content:
    content = content.replace(old_block, new_block)
    with open(path, 'w') as f:
        f.write(content)
    print("Fixed ConcurrentProgram.java lock scanning")
else:
    print("Lock scanning pattern not found - may already be fixed")
