#!/usr/bin/env python3
"""Convert a raw binary file to hex word format (one 32-bit LE word per line)."""
import struct
import sys

def main():
    in_path = sys.argv[1]
    out_path = sys.argv[2]
    with open(in_path, 'rb') as f:
        data = f.read()
    with open(out_path, 'w') as f:
        for i in range(0, len(data), 4):
            chunk = data[i:i+4]
            if len(chunk) < 4:
                chunk = chunk + b'\x00' * (4 - len(chunk))
            word = struct.unpack('<I', chunk)[0]
            f.write(f'{word:08x}\n')

if __name__ == '__main__':
    main()
