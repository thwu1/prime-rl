#!/usr/bin/env python3
"""Generate Intel HEX firmware files for flash planner testing."""
import os


def ihex_record(record_type, address, data=b''):
    """Create an Intel HEX record string."""
    byte_count = len(data)
    record = f'{byte_count:02X}{address:04X}{record_type:02X}'
    record += data.hex().upper()
    all_bytes = bytes.fromhex(record)
    checksum = (256 - sum(all_bytes) % 256) % 256
    return f':{record}{checksum:02X}'


def extended_linear_address(base_addr):
    """Create extended linear address record (type 04)."""
    upper = (base_addr >> 16) & 0xFFFF
    return ihex_record(0x04, 0x0000, upper.to_bytes(2, 'big'))


def eof_record():
    return ihex_record(0x01, 0x0000)


def write_hex_file(path, segments):
    """Write Intel HEX file from list of (address, data) segments."""
    lines = []
    current_ela = None

    for addr, data in segments:
        offset = 0
        while offset < len(data):
            current_addr = addr + offset
            ela = current_addr & 0xFFFF0000

            if ela != current_ela:
                lines.append(extended_linear_address(ela))
                current_ela = ela

            local_addr = current_addr & 0xFFFF
            bytes_to_boundary = 0x10000 - local_addr
            chunk_size = min(16, len(data) - offset, bytes_to_boundary)

            chunk = data[offset:offset + chunk_size]
            lines.append(ihex_record(0x00, local_addr, chunk))
            offset += chunk_size

    lines.append(eof_record())

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


OUTPUT = '/app/firmware'

# 1. small.hex — 1024 bytes at 0x08000000 (STM32F4, fits in first 16KB sector)
write_hex_file(f'{OUTPUT}/small.hex', [
    (0x08000000, bytes(range(256)) * 4)
])

# 2. cross_boundary.hex — 16KB at 0x0800E000, crosses 16KB->64KB sector boundary
write_hex_file(f'{OUTPUT}/cross_boundary.hex', [
    (0x0800E000, bytes([0xAA, 0xBB, 0xCC, 0xDD] * 4096))
])

# 3. multi_region.hex — data in both Bank A and Bank B of dual_bank target
write_hex_file(f'{OUTPUT}/multi_region.hex', [
    (0x08000000, bytes([0x11] * 512)),
    (0x10000000, bytes([0x22] * 256))
])

# 4. non_contiguous.hex — two regions in STM32F4 (code + data, far apart)
write_hex_file(f'{OUTPUT}/non_contiguous.hex', [
    (0x08000000, bytes([0xC0, 0xDE] * 2048)),
    (0x080E0000, bytes([0xDA, 0x7A] * 1024))
])

# 5. unaligned.hex — 500 bytes starting mid-page at 0x08000300
write_hex_file(f'{OUTPUT}/unaligned.hex', [
    (0x08000300, bytes([0x42] * 500))
])

# 6. all_ff.hex — 4096 bytes of 0xFF (should produce no operations for 0xFF-erased chips)
write_hex_file(f'{OUTPUT}/all_ff.hex', [
    (0x08000000, bytes([0xFF] * 4096))
])

# 7. overflow.hex — 2048 bytes at 0x080FFC00 (extends past STM32F4 flash end at 0x08100000)
write_hex_file(f'{OUTPUT}/overflow.hex', [
    (0x080FFC00, bytes([0x55] * 2048))
])

# 8. nrf_basic.hex — 6000 bytes at 0x00000000 (nRF52840, uniform 4KB sectors)
write_hex_file(f'{OUTPUT}/nrf_basic.hex', [
    (0x00000000, bytes([i & 0xFF for i in range(6000)]))
])

print("Generated firmware files successfully")
