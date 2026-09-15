#!/usr/bin/env python3
"""Generate firmware files and current flash state dumps for optimizer testing."""
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


def srec_record(rec_type, address, data=b''):
    """Create a Motorola S-record line."""
    if rec_type in (0, 1, 5, 9):
        addr_bytes = address.to_bytes(2, 'big')
    elif rec_type in (2, 8):
        addr_bytes = address.to_bytes(3, 'big')
    elif rec_type in (3, 7):
        addr_bytes = address.to_bytes(4, 'big')
    else:
        raise ValueError(f"Unknown SREC type: {rec_type}")
    payload = addr_bytes + data
    byte_count = len(payload) + 1
    all_bytes = bytes([byte_count]) + payload
    checksum = (~sum(all_bytes)) & 0xFF
    return f'S{rec_type}{byte_count:02X}{payload.hex().upper()}{checksum:02X}'


def write_srec_file(path, segments):
    """Write Motorola S-record file from list of (address, data) segments."""
    lines = []
    lines.append(srec_record(0, 0, b'HDR'))
    for addr, data in segments:
        offset = 0
        while offset < len(data):
            chunk_size = min(16, len(data) - offset)
            chunk = data[offset:offset + chunk_size]
            current_addr = addr + offset
            if current_addr < 0x10000:
                lines.append(srec_record(1, current_addr, chunk))
            elif current_addr < 0x1000000:
                lines.append(srec_record(2, current_addr, chunk))
            else:
                lines.append(srec_record(3, current_addr, chunk))
            offset += chunk_size
    lines.append(srec_record(7, 0))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def write_binary_dump(path, data):
    """Write raw binary file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)


FW = '/app/firmware'
CS = '/app/current_state'

# Flash sizes
STM32_FLASH_SIZE = 0x100000   # 1MB
NRF_FLASH_SIZE = 0x100000     # 1MB
BANK_A_SIZE = 0x40000          # 256KB
BANK_B_SIZE = 0x10000          # 64KB

# ===== Firmware files (Intel HEX) =====

# small.hex: 1024 bytes of 0x42 at 0x08000000
small_data = bytes([0x42] * 1024)
write_hex_file(f'{FW}/small.hex', [(0x08000000, small_data)])

# cross_boundary.hex: 16KB at 0x0800E000, crossing 16KB->64KB sector boundary
cross_data = bytes([0xAA, 0xBB, 0xCC, 0xDD] * 4096)
write_hex_file(f'{FW}/cross_boundary.hex', [(0x0800E000, cross_data)])

# non_contiguous.hex: two segments far apart in STM32F4
write_hex_file(f'{FW}/non_contiguous.hex', [
    (0x08000000, bytes([0xC0, 0xDE] * 2048)),
    (0x080E0000, bytes([0xDA, 0x7A] * 1024))
])

# unaligned.hex: 500 bytes mid-page at 0x08000300
write_hex_file(f'{FW}/unaligned.hex', [(0x08000300, bytes([0x42] * 500))])

# all_ff.hex: 4096 bytes of 0xFF at 0x08000000
write_hex_file(f'{FW}/all_ff.hex', [(0x08000000, bytes([0xFF] * 4096))])

# overflow.hex: extends past STM32F4 flash end
write_hex_file(f'{FW}/overflow.hex', [(0x080FFC00, bytes([0x55] * 2048))])

# nrf_basic.hex: 6000 bytes of 0x42 at 0x00000000
write_hex_file(f'{FW}/nrf_basic.hex', [(0x00000000, bytes([0x42] * 6000))])

# nrf_incremental.hex: 4096 bytes of 0x00 at 0x00000000
write_hex_file(f'{FW}/nrf_incremental.hex', [(0x00000000, bytes([0x00] * 4096))])

# nrf_erase_needed.hex: 4096 bytes of 0xF0 at 0x00000000
write_hex_file(f'{FW}/nrf_erase_needed.hex', [(0x00000000, bytes([0xF0] * 4096))])

# nrf_mixed.hex: 8192 bytes of 0xF0 at 0x00000000 (two sectors)
write_hex_file(f'{FW}/nrf_mixed.hex', [(0x00000000, bytes([0xF0] * 8192))])

# sector_test.hex: 16KB at 0x08000000, first 8KB=0x42, next 8KB=0xF0
write_hex_file(f'{FW}/sector_test.hex', [
    (0x08000000, bytes([0x42] * 8192) + bytes([0xF0] * 8192))
])

# ===== Firmware files (Motorola S-record) =====

# multi_region.srec: data in both banks of dual_bank target
write_srec_file(f'{FW}/multi_region.srec', [
    (0x08000000, bytes([0x11] * 512)),
    (0x10000000, bytes([0x22] * 256))
])

# cross_boundary.srec: same data as cross_boundary.hex in SREC format
write_srec_file(f'{FW}/cross_boundary.srec', [(0x0800E000, cross_data)])

# ===== Current flash state dumps =====

# stm32f4_clean.bin: clean STM32F4 flash (all 0xFF)
write_binary_dump(f'{CS}/stm32f4_clean.bin', bytes([0xFF] * STM32_FLASH_SIZE))

# stm32f4_small.bin: has small.hex already programmed (for re-flash test)
stm32_small = bytearray([0xFF] * STM32_FLASH_SIZE)
stm32_small[0:len(small_data)] = small_data
write_binary_dump(f'{CS}/stm32f4_small.bin', bytes(stm32_small))

# stm32f4_sector_test.bin: first 8KB matches firmware, next 8KB conflicts
stm32_sector = bytearray([0xFF] * STM32_FLASH_SIZE)
stm32_sector[0:8192] = bytes([0x42] * 8192)
stm32_sector[8192:16384] = bytes([0x0F] * 8192)
write_binary_dump(f'{CS}/stm32f4_sector_test.bin', bytes(stm32_sector))

# nrf52_clean.bin: clean nRF52 flash (all 0xFF)
write_binary_dump(f'{CS}/nrf52_clean.bin', bytes([0xFF] * NRF_FLASH_SIZE))

# nrf52_partial.bin: first 4096 bytes = 0xF0, rest 0xFF
nrf_partial = bytearray([0xFF] * NRF_FLASH_SIZE)
nrf_partial[0:4096] = bytes([0xF0] * 4096)
write_binary_dump(f'{CS}/nrf52_partial.bin', bytes(nrf_partial))

# nrf52_conflict.bin: first 4096 bytes = 0x0F, rest 0xFF
nrf_conflict = bytearray([0xFF] * NRF_FLASH_SIZE)
nrf_conflict[0:4096] = bytes([0x0F] * 4096)
write_binary_dump(f'{CS}/nrf52_conflict.bin', bytes(nrf_conflict))

# nrf52_mixed.bin: first 4096 = 0x0F (conflicts), next 4096 = 0xFF (clean)
nrf_mixed = bytearray([0xFF] * NRF_FLASH_SIZE)
nrf_mixed[0:4096] = bytes([0x0F] * 4096)
write_binary_dump(f'{CS}/nrf52_mixed.bin', bytes(nrf_mixed))

# dual_bank_clean.bin: Bank A (256KB of 0xFF) + Bank B (64KB of 0x00)
dual_clean = bytes([0xFF] * BANK_A_SIZE) + bytes([0x00] * BANK_B_SIZE)
write_binary_dump(f'{CS}/dual_bank_clean.bin', dual_clean)

print("Generated all firmware and current state files successfully")
