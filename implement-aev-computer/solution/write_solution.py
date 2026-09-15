#!/usr/bin/env python3
"""Generate the AEV computer solution at /app/aev_computer.py."""

import shutil
import os

# Copy the implementation
shutil.copy("/solution/aev_impl.py", "/app/aev_computer.py")
print("Solution written to /app/aev_computer.py")
