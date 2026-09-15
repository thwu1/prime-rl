#!/usr/bin/env python3
"""
Fix the 5 bugs in mseed3pack.c:

1. CRC polynomial: CRC-32 (0xEDB88320) -> CRC-32C (0x82F63B78)
2. 5x6-bit shift spacing: 5-bit steps -> 6-bit steps
3. 2x15-bit mask: 14-bit (0x3FFF) -> 15-bit (0x7FFF)
4. Frame 0 X0/Xn: swapped word positions -> correct positions
5. Header encoding: DE_STEIM1 -> DE_STEIM2

"""

with open('/app/mseed3pack.c', 'r') as f:
    lines = f.readlines()

result = []
for line in lines:
    # Bug 1: CRC polynomial - CRC-32 vs CRC-32C
    line = line.replace('0xEDB88320', '0x82F63B78')

    # Bug 5: Header encoding type
    line = line.replace('record[15] = DE_STEIM1', 'record[15] = DE_STEIM2')

    # Bug 3: 2x15-bit mask (0x3FFF is unique to 2x15b section)
    line = line.replace('0x3FFFu)', '0x7FFFu)')

    # Bug 2: 5x6-bit shift spacing (0x3Fu patterns are unique to 5x6b section)
    line = line.replace('0x3Fu) << 5;', '0x3Fu) << 6;')
    line = line.replace('0x3Fu) << 10;', '0x3Fu) << 12;')
    line = line.replace('0x3Fu) << 15;', '0x3Fu) << 18;')
    line = line.replace('0x3Fu) << 20;', '0x3Fu) << 24;')

    # Bug 4: X0/Xn frame positions swapped
    line = line.replace(
        'frameptr[2] = (uint32_t)input[0];',
        'frameptr[1] = (uint32_t)input[0];'
    )
    line = line.replace(
        'Xnp = (int32_t *)&frameptr[1];',
        'Xnp = (int32_t *)&frameptr[2];'
    )

    result.append(line)

with open('/app/mseed3pack.c', 'w') as f:
    f.writelines(result)

print("All 5 bugs fixed in mseed3pack.c")
