A Flask web application at `/app/webapp/app.py` has 12 route handlers. Some contain security vulnerabilities across multiple CWE categories; others apply proper mitigations against the same attack classes.

Build a Python program at `/app/analyze.py` that examines Flask application source files without executing them and identifies security vulnerabilities. The program must accept two CLI arguments: an input Python file path and an output JSON file path.

The program must detect vulnerabilities in these CWE categories: CWE-078 (command injection), CWE-079 (XSS), CWE-089 (SQL injection), CWE-022 (path traversal), CWE-918 (SSRF). It must not produce false positives on routes that correctly mitigate these vulnerability classes. It must correctly identify vulnerabilities even when user-controlled data reaches a dangerous operation indirectly through helper functions or class methods defined in the same file. The program must generalize to arbitrary Flask application code, not just the provided sample.

Output JSON format:
```json
{"findings": [{"cwe": "CWE-XXX", "function": "<route_handler_name>", "sink_type": "<category>"}]}
```

`sink_type` must be one of: `sql_injection`, `command_injection`, `path_traversal`, `xss`, `ssrf`.

After building the program, run: `python3 /app/analyze.py /app/webapp/app.py /app/results.json`