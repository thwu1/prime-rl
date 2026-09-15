#!/usr/bin/env python3
"""Create Python ctypes bindings for the number theory shared library."""

BINDINGS_SOURCE = '''\
"""Python ctypes bindings for libntsum number-theoretic computation library."""
import ctypes

_lib = ctypes.CDLL('/app/build/libntsum.so')

for _name in ['ntsum_prime_count', 'ntsum_mertens', 'ntsum_totient_sum',
              'ntsum_squarefree_count', 'ntsum_liouville_sum']:
    _fn = getattr(_lib, _name)
    _fn.argtypes = [ctypes.c_longlong]
    _fn.restype = ctypes.c_longlong

ntsum_prime_count = _lib.ntsum_prime_count
ntsum_mertens = _lib.ntsum_mertens
ntsum_totient_sum = _lib.ntsum_totient_sum
ntsum_squarefree_count = _lib.ntsum_squarefree_count
ntsum_liouville_sum = _lib.ntsum_liouville_sum
'''

def main():
    with open('/app/ntsum_bindings.py', 'w') as f:
        f.write(BINDINGS_SOURCE)
    print("Created /app/ntsum_bindings.py")

if __name__ == '__main__':
    main()
