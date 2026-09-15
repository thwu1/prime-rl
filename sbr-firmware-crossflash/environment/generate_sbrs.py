#!/usr/bin/env python3
"""Generate SBR binary dumps for the firmware crossflash task."""

import struct
import json
import os


def make_sbr(phy_config, vid, pid, interface, phy_lane, config_flag,
             sub_vid, sub_pid, timing, sas_addr):
    """Create a 256-byte SBR binary with correct checksums and mirror.

    SBR layout:
      0x00-0x0B: PHY analog configuration (12 bytes)
      0x0C-0x0D: PCI Vendor ID (little-endian)
      0x0E-0x0F: PCI Product ID (little-endian)
      0x10:      Interface mode (0x00=IT/IR, 0x10=iMR)
      0x11:      Reserved
      0x12:      PHY lane enable
      0x13:      Config flag
      0x14-0x15: Subsystem Vendor ID (little-endian)
      0x16-0x17: Subsystem Product ID (little-endian)
      0x18-0x3F: Reserved (zeros)
      0x40-0x4A: Electrical timing parameters (11 bytes)
      0x4B:      Primary checksum (sum of 0x00-0x4B mod 256 == 0x5B)
      0x4C-0x97: Mirror of bytes 0x00-0x4B (Mfg Page 2)
      0x98-0xD7: Reserved (zeros)
      0xD8-0xDF: SAS World Wide Name (8 bytes)
      0xE0-0xEE: Reserved (zeros)
      0xEF:      SAS checksum (sum of 0xD8-0xEF mod 256 == 0x5B)
      0xF0-0xFF: Reserved (zeros)
    """
    sbr = bytearray(256)

    # PHY configuration (0x00-0x0B)
    sbr[0x00:0x0C] = phy_config

    # PCI IDs (little-endian)
    struct.pack_into('<H', sbr, 0x0C, vid)
    struct.pack_into('<H', sbr, 0x0E, pid)

    # Interface mode
    sbr[0x10] = interface

    # PHY lane enable and config flag
    sbr[0x12] = phy_lane
    sbr[0x13] = config_flag

    # Subsystem IDs (little-endian)
    struct.pack_into('<H', sbr, 0x14, sub_vid)
    struct.pack_into('<H', sbr, 0x16, sub_pid)

    # Timing parameters (0x40-0x4A)
    sbr[0x40:0x4B] = timing

    # Primary checksum at 0x4B
    s = sum(sbr[0x00:0x4B]) % 256
    sbr[0x4B] = (0x5B - s) % 256

    # Mirror bytes 0x00-0x4B to 0x4C-0x97
    sbr[0x4C:0x98] = sbr[0x00:0x4C]

    # SAS address (0xD8-0xDF)
    sbr[0xD8:0xE0] = sas_addr

    # SAS checksum at 0xEF
    s = sum(sbr[0xD8:0xEF]) % 256
    sbr[0xEF] = (0x5B - s) % 256

    return bytes(sbr)


# PHY configuration variants (board-specific analog tuning)
PHY_STD = bytes([0x61, 0xf6, 0x22, 0x61, 0xf7, 0x36,
                 0x4f, 0xb3, 0xf8, 0x00, 0xd7, 0x91])
PHY_DELL = bytes([0x61, 0xf6, 0x22, 0x61, 0xf7, 0x36,
                  0x4f, 0xb3, 0xf8, 0x00, 0xd8, 0x91])

# Timing parameter variants
TIME_STD = bytes([0x00, 0x0c, 0x5d, 0x00, 0x5c, 0x30,
                  0x5a, 0x14, 0x75, 0x05, 0x10])
TIME_DELL = bytes([0x00, 0x0c, 0x5d, 0x00, 0x5c, 0x30,
                   0x5a, 0x14, 0x75, 0x05, 0x11])


os.makedirs('/app/dumps', exist_ok=True)
os.makedirs('/app/output', exist_ok=True)

samples = {}

# Supermicro SAS9211-8i in IT/IR mode - working, all 8 ports
samples['supermicro_itir.bin'] = make_sbr(
    PHY_STD, 0x1000, 0x0072, 0x00, 0x07, 0x01,
    0x15D9, 0x0400, TIME_STD,
    bytes([0x50, 0x00, 0x05, 0x1e, 0x00, 0x3a, 0x22, 0x10]))

# Supermicro SAS9211-8i in iMR/MegaRAID mode - working, all 8 ports
samples['supermicro_imr.bin'] = make_sbr(
    PHY_STD, 0x1000, 0x0073, 0x10, 0x07, 0x01,
    0x15D9, 0x0400, TIME_STD,
    bytes([0x50, 0x00, 0x05, 0x1e, 0x00, 0x3a, 0x22, 0x11]))

# Fujitsu D2607 in iMR mode - only 4 ports working
samples['fujitsu_d2607_original.bin'] = make_sbr(
    PHY_STD, 0x1000, 0x0073, 0x10, 0x04, 0x01,
    0x1734, 0x1177, TIME_STD,
    bytes([0x50, 0x00, 0x05, 0x1e, 0x00, 0x4b, 0x91, 0xa2]))

# Dell PERC H200 in IT mode - working, all 8 ports, different tuning
# Note: config_flag 0x02 is vendor-specific (differs from standard 0x01)
samples['dell_h200.bin'] = make_sbr(
    PHY_DELL, 0x1000, 0x0072, 0x00, 0x07, 0x02,
    0x1028, 0x1F1C, TIME_DELL,
    bytes([0x50, 0x00, 0x1f, 0xe8, 0x00, 0x12, 0xce, 0x40]))

# LSI generic template - IT/IR mode, no SAS address programmed
# Simulate partial EEPROM degradation: corrupt one byte in the mirror
# region ONLY. Primary checksum remains valid but mirror doesn't match.
lsi = bytearray(make_sbr(
    PHY_STD, 0x1000, 0x0072, 0x00, 0x07, 0x01,
    0x1000, 0x3020, TIME_STD,
    bytes(8)))
# Corrupt mirror byte at 0x5A (corresponds to primary 0x0E = PCI PID low byte)
# Primary shows PID 0x0072, mirror shows PID 0x0073 — subtle inconsistency
lsi[0x5A] = (lsi[0x5A] + 0x01) % 256
samples['lsi_generic_template.bin'] = bytes(lsi)

# IBM ServeRAID M1015 - corrupt a timing byte AFTER mirror was written.
# This breaks the primary checksum AND makes mirror inconsistent with primary.
# Manifest deliberately does NOT flag this as suspect — it's a silent failure.
ibm = bytearray(make_sbr(
    PHY_STD, 0x1000, 0x0073, 0x10, 0x07, 0x01,
    0x1014, 0x0412, TIME_STD,
    bytes([0x50, 0x00, 0x0a, 0xc5, 0x00, 0x19, 0xf7, 0x88])))
ibm[0x42] = (ibm[0x42] + 0x03) % 256
samples['ibm_m1015.bin'] = bytes(ibm)

# Write all sample binaries
for name, data in samples.items():
    with open(f'/app/dumps/{name}', 'wb') as f:
        f.write(data)

# Write manifest — NO corruption hints for IBM or LSI template
manifest = {
    "description": "SBR (Serial Boot ROM) dumps from LSI SAS2008-based storage controllers. Each is a 256-byte EEPROM image that configures the controller's PCI identity, operating mode, and SAS addressing.",
    "samples": [
        {
            "filename": "supermicro_itir.bin",
            "vendor": "Supermicro",
            "model": "SAS9211-8i",
            "firmware_mode": "IT/IR (HBA passthrough)",
            "status": "working",
            "notes": "All 8 SAS ports detected and operational"
        },
        {
            "filename": "supermicro_imr.bin",
            "vendor": "Supermicro",
            "model": "SAS9211-8i",
            "firmware_mode": "iMR (MegaRAID)",
            "status": "working",
            "notes": "All 8 SAS ports detected and operational"
        },
        {
            "filename": "fujitsu_d2607_original.bin",
            "vendor": "Fujitsu",
            "model": "D2607",
            "firmware_mode": "iMR (MegaRAID)",
            "status": "partial",
            "notes": "Only 4 of 8 SAS ports detected; second SFF-8087 connector dead after crossflash attempts with standard SBR files from other vendors"
        },
        {
            "filename": "dell_h200.bin",
            "vendor": "Dell",
            "model": "PERC H200",
            "firmware_mode": "IT (HBA passthrough)",
            "status": "working",
            "notes": "All 8 SAS ports detected; board uses vendor-specific configuration and analog tuning parameters"
        },
        {
            "filename": "ibm_m1015.bin",
            "vendor": "IBM",
            "model": "ServeRAID M1015",
            "firmware_mode": "iMR (MegaRAID)",
            "status": "working",
            "notes": "All 8 SAS ports detected and operational"
        },
        {
            "filename": "lsi_generic_template.bin",
            "vendor": "LSI",
            "model": "Generic SAS2008 reference",
            "firmware_mode": "IT/IR (HBA passthrough)",
            "status": "template",
            "notes": "Factory reference template SBR with no unique SAS address programmed"
        }
    ]
}

with open('/app/dumps/manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

# Write target specification — high-level requirements only, no format details
target_spec = {
    "description": "Produce an SBR for crossflashing the Fujitsu D2607 from iMR (MegaRAID) mode to IT/IR (HBA) mode with all 8 SAS ports enabled.",
    "base_dump": "fujitsu_d2607_original.bin",
    "requirements": {
        "target_firmware_mode": "IT/IR (HBA passthrough)",
        "port_count": 8,
        "preserve_board_identity": "Keep Fujitsu subsystem vendor/product IDs unchanged",
        "preserve_sas_address": "Keep original SAS World Wide Name from the Fujitsu dump",
        "preserve_hardware_calibration": "Keep board-specific analog and timing parameters unchanged",
        "all_integrity_checks_valid": "All internal data integrity mechanisms must pass validation"
    },
    "output_path": "/app/output/target.bin",
    "output_size_bytes": 256
}

with open('/app/target_spec.json', 'w') as f:
    json.dump(target_spec, f, indent=2)

# Verification of generated data (only for uncorrupted samples)
for name, data in samples.items():
    if name in ('ibm_m1015.bin', 'lsi_generic_template.bin'):
        continue  # known corrupted by design
    assert len(data) == 256, f"{name}: wrong size"
    assert sum(data[0x00:0x4C]) % 256 == 0x5B, f"{name}: bad primary checksum"
    assert data[0x4C:0x98] == data[0x00:0x4C], f"{name}: bad mirror"
    assert sum(data[0xD8:0xF0]) % 256 == 0x5B, f"{name}: bad SAS checksum"

print("All SBR samples generated and verified successfully.")
