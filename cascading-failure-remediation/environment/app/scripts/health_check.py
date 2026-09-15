#!/usr/bin/env python3
"""Health Check - verifies that all service-control instances and the
gateway are responding to health probes."""
import sys
import requests

ENDPOINTS = [
    ('service_control_1', 'http://localhost:5001/health'),
    ('service_control_2', 'http://localhost:5002/health'),
    ('service_control_3', 'http://localhost:5003/health'),
    ('gateway',           'http://localhost:5000/health'),
]


def main():
    all_ok = True
    for name, url in ENDPOINTS:
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                data = r.json()
                print(f"  {name}: HEALTHY  {data}")
            else:
                print(f"  {name}: UNHEALTHY (HTTP {r.status_code})")
                all_ok = False
        except Exception as exc:
            print(f"  {name}: DOWN ({exc})")
            all_ok = False

    if all_ok:
        print("\nAll services healthy.")
    else:
        print("\nSome services are unhealthy or unreachable.")
        sys.exit(1)


if __name__ == '__main__':
    main()
