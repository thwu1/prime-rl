#!/usr/bin/env python3
"""Launch the compiled API server from bytecode."""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("server", "/app/api/server.pyc")
if spec is None:
    print("ERROR: Cannot load /app/api/server.pyc", file=sys.stderr)
    sys.exit(1)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.app.run(host='0.0.0.0', port=5000, debug=False)
