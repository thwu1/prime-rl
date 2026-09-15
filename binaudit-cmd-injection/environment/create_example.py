#!/usr/bin/env python3
"""Create a sample .bscan file for testing binaudit."""
import struct

def create_bscan(sections, path):
    data = bytearray()
    data += b'BSCN'
    data += struct.pack('<I', 1)
    data += struct.pack('<I', len(sections))
    data += struct.pack('<I', 0)
    for name, vaddr, vsize, offset, rawsize, chars, align in sections:
        name_bytes = name.encode('ascii').ljust(8, b'\x00')[:8]
        data += name_bytes
        data += struct.pack('<I', vaddr)
        data += struct.pack('<I', vsize)
        data += struct.pack('<I', offset)
        data += struct.pack('<I', rawsize)
        data += struct.pack('<I', chars)
        data += struct.pack('<I', align)
    with open(path, 'wb') as f:
        f.write(data)

sections = [
    ('.text',   0x00401000, 0x2000, 0x0200, 0x1800, 0x60000020, 16),
    ('.rdata',  0x00403000, 0x1000, 0x2000, 0x0800, 0x40000040, 16),
    ('.data',   0x00404000, 0x1000, 0x3000, 0x0600, 0xC0000040, 16),
    ('.bss',    0x00405000, 0x0500, 0x0000, 0x0000, 0xC0000080, 16),
]

create_bscan(sections, '/app/samples/example.bscan')
print('[+] Created /app/samples/example.bscan')
