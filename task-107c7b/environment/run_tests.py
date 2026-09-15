#!/usr/bin/env python3
"""
Test runner for TCP-AO KDF implementation against RFC 9235 test vectors.
Run this to check your implementation: python3 /app/run_tests.py
"""

import json
import sys
import os

sys.path.insert(0, '/app')
from tcp_ao import derive_traffic_key

def run_tests():
    with open('/app/vectors.json') as f:
        data = json.load(f)

    master_key = data['master_key_ascii'].encode('ascii')
    passed = 0
    failed = 0
    total = 0

    for conn in data['connections']:
        client_ip = conn['client_ip']
        server_ip = conn['server_ip']
        client_port = conn['client_port']
        server_port = conn['server_port']
        client_isn = int(conn['client_isn_hex'], 16)
        server_isn = int(conn['server_isn_hex'], 16)
        kdf_alg = conn['kdf_alg']

        key_params = {
            'Send_SYN': (client_ip, server_ip, client_port, server_port, client_isn, 0),
            'Receive_SYN': (server_ip, client_ip, server_port, client_port, server_isn, client_isn),
            'Send_other': (client_ip, server_ip, client_port, server_port, client_isn, server_isn),
            'Receive_other': (server_ip, client_ip, server_port, client_port, server_isn, client_isn),
        }

        for key_type, expected_hex in conn['traffic_keys'].items():
            total += 1
            src_ip, dst_ip, src_port, dst_port, src_isn, dst_isn = key_params[key_type]

            try:
                result = derive_traffic_key(kdf_alg, master_key,
                                            src_ip, dst_ip,
                                            src_port, dst_port,
                                            src_isn, dst_isn)
                result_hex = result.hex()
                if result_hex == expected_hex:
                    passed += 1
                    print(f"  PASS  {conn['id']}.{key_type}")
                else:
                    failed += 1
                    print(f"  FAIL  {conn['id']}.{key_type}")
                    print(f"        expected: {expected_hex}")
                    print(f"        got:      {result_hex}")
            except Exception as e:
                failed += 1
                print(f"  ERROR {conn['id']}.{key_type}: {e}")

    print(f"\n{'='*50}")
    print(f"Results: {passed}/{total} passed, {failed}/{total} failed")
    return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
