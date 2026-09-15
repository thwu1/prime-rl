#!/usr/bin/env python3
"""
Validation harness for SIP ALG packet boundary exploitation.

Usage:  python3 /app/validate.py
        python3 /app/validate.py --debug

Loads /app/exploit.py, runs every scenario from /app/config.json,
and reports whether each one triggers ALG pinhole creation.

"""

import json
import os
import sys
import importlib.util
import traceback


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    debug = '--debug' in sys.argv

    sys.path.insert(0, '/app')
    from alg_simulator import SIPConnectionTracker
    from tcp_engine import TCPSegmenter

    if not os.path.exists('/app/exploit.py'):
        print("ERROR: /app/exploit.py not found")
        return False

    exploit = _load("exploit", "/app/exploit.py")
    if not hasattr(exploit, 'generate_payload'):
        print("ERROR: exploit.py must define generate_payload(scenario)")
        return False

    with open('/app/config.json') as f:
        config = json.load(f)

    all_pass = True
    for sc in config['scenarios']:
        sid = sc['id']
        try:
            payload = exploit.generate_payload(sc)

            boundary = sc['boundary']
            headers = sc['http_headers_template'].replace('{boundary}', boundary)
            body = payload if isinstance(payload, bytes) else payload.encode('utf-8')
            headers = headers.replace('{content_length}', str(len(body)))
            full_stream = headers.encode('utf-8') + body

            segments = TCPSegmenter(sc['mss']).segment(full_stream)

            # check raw alignment
            reg_found = any(
                seg.decode('utf-8', errors='ignore').startswith('REGISTER ')
                for seg in segments
            )
            if not reg_found:
                print(f"  {sid}: FAIL - REGISTER not at segment boundary")
                all_pass = False
                continue

            tracker = SIPConnectionTracker(
                strict=sc.get('strict_mode', False), debug=debug
            )
            expectations = tracker.process_stream(segments, sc['internal_ip'])

            if not expectations:
                print(f"  {sid}: FAIL - no pinhole (ALG rejected packet)")
                all_pass = False
                continue

            port = expectations[0]['contact_port']
            if port != sc['target_port']:
                print(f"  {sid}: FAIL - port {port} != expected {sc['target_port']}")
                all_pass = False
                continue

            print(f"  {sid}: PASS  (pinhole {expectations[0]['contact_ip']}:{port})")

        except Exception:
            print(f"  {sid}: ERROR")
            traceback.print_exc()
            all_pass = False

    print()
    print("RESULT:", "ALL PASS" if all_pass else "SOME FAILED")
    return all_pass


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
