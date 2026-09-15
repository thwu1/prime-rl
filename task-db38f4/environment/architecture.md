# Firmware Update Simulator — Architecture

## Overview

This simulator models a firmware update system based on the Secure
Binary 2 (SB2) format used in embedded microcontrollers for secure
firmware delivery. It processes SB2-format update files through a
multi-stage security verification pipeline before accepting an update.

## Components

| Path | Description |
|------|-------------|
| `/app/firmware_sim` | Compiled simulator binary |
| `/app/src/main.c` | Application entry point (source provided) |
| `/app/include/sb2_format.h` | SB2 header structure definitions |
| `/app/lib/sb2_parser.o` | Pre-compiled update parser (vendor-supplied; source not available) |
| `/app/docs/architecture.md` | This document |

The binary was built with:

    gcc -O1 -fno-stack-protector main.c lib/sb2_parser.o -o firmware_sim -Iinclude/

## SB2 Update Format

Updates follow the Secure Binary 2 format. The file begins with a
128-byte header (8 blocks of 16 bytes) whose structure is defined in
`sb2_format.h`. Key header fields include:

- **nonce** — random 128-bit value
- **m_signature / m_signature2** — format magic identifiers
- **m_majorVersion** — must be 2
- **m_headerBlocks** — number of blocks occupied by the header
- **m_keyBlobBlock** — block offset where the key blob begins in the file

## Security Pipeline

The pre-compiled parser validates incoming update files through
multiple sequential stages. All stages must pass for an update to be
accepted. The parser maintains internal state that is not exposed
through the shipped headers. Error messages indicate which stage
rejected the file but do not disclose expected values.

On success the simulator prints **UPDATE ACCEPTED** followed by
diagnostic output including the DICE UDS.

## DICE Unique Device Secret

Each device contains a 32-byte Unique Device Secret (UDS) initialised
during system startup. The UDS serves as the root secret for the
device's identity and attestation protocol (DICE). Under normal
operation, the UDS is accessible only through authenticated firmware
paths.
