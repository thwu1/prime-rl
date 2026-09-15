
import sys
import os

# Ensure /app modules (ir, emulator, test_programs, regalloc) are importable
sys.path.insert(0, '/app')
os.environ.setdefault('PYTHONPATH', '/app')
