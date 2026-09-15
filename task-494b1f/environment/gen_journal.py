#!/usr/bin/env python3
"""Generate the binary edit journal for the piece table task."""
import struct
import sys

out = bytearray()
# Header
out += b"PTEDIT"
out += struct.pack('BB', 0x01, 0x00)

# INSERT at 0: "The quick brown fox\njumps over the lazy dog\n"
text = "The quick brown fox\njumps over the lazy dog\n".encode('utf-8')
out.append(0x01)
out += struct.pack('<II', 0, len(text))
out += text

# SNAPSHOT 1
out.append(0x03)
out += struct.pack('<I', 1)

# INSERT at 20: "quickly "
text = "quickly ".encode('utf-8')
out.append(0x01)
out += struct.pack('<II', 20, len(text))
out += text

# SNAPSHOT 2
out.append(0x03)
out += struct.pack('<I', 2)

# DELETE at 10, length 6
out.append(0x02)
out += struct.pack('<II', 10, 6)

# INSERT at 10: "red "
text = "red ".encode('utf-8')
out.append(0x01)
out += struct.pack('<II', 10, len(text))
out += text

# SNAPSHOT 3
out.append(0x03)
out += struct.pack('<I', 3)

# UNDO
out.append(0x04)

# UNDO
out.append(0x04)

# INSERT at 9: ","
text = ",".encode('utf-8')
out.append(0x01)
out += struct.pack('<II', 9, len(text))
out += text

# SNAPSHOT 4
out.append(0x03)
out += struct.pack('<I', 4)

# END
out.append(0xFF)

sys.stdout.buffer.write(bytes(out))
