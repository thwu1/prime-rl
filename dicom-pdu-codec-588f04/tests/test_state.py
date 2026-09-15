
"""Tests for the DICOM Upper Layer PDU codec."""

import sys
import os
import struct
import json
import subprocess
sys.path.insert(0, '/app')
import pytest
from dicom_codec import decode_pdu, encode_pdu, negotiate_roles, fragment_pdata, analyze_stream
from gen_captures import build_dicom_pcap

# ============================================================================
# Pre-encoded PDU byte fixtures from real DICOM implementations
# ============================================================================

# A-ASSOCIATE-RQ: basic Verification SOP Class, single context
A_ASSOCIATE_RQ_BASIC = (
    b"\x01\x00\x00\x00\x00\xd1\x00\x01\x00\x00\x41\x4e\x59\x2d"
    b"\x53\x43\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x45\x43"
    b"\x48\x4f\x53\x43\x55\x20\x20\x20\x20\x20\x20\x20\x20\x20"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e\x32\x2e\x38\x34"
    b"\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e\x31\x2e"
    b"\x31\x20\x00\x00\x2e\x01\x00\x00\x00\x30\x00\x00\x11\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31"
    b"\x2e\x31\x40\x00\x00\x11\x31\x2e\x32\x2e\x38\x34\x30\x2e"
    b"\x31\x30\x30\x30\x38\x2e\x31\x2e\x32\x50\x00\x00\x3e\x51"
    b"\x00\x00\x04\x00\x00\x3f\xfe\x52\x00\x00\x20\x31\x2e\x32"
    b"\x2e\x38\x32\x36\x2e\x30\x2e\x31\x2e\x33\x36\x38\x30\x30"
    b"\x34\x33\x2e\x39\x2e\x33\x38\x31\x31\x2e\x30\x2e\x39\x2e"
    b"\x30\x55\x00\x00\x0e\x50\x59\x4e\x45\x54\x44\x49\x43\x4f"
    b"\x4d\x5f\x30\x39\x30"
)

# A-ASSOCIATE-RQ with User Identity (username) + Async Ops Window
A_ASSOCIATE_RQ_USER_ASYNC = (
    b"\x01\x00\x00\x00\x00\xed\x00\x01\x00\x00\x41\x4e\x59\x2d\x53\x43"
    b"\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x45\x43\x48\x4f\x53\x43"
    b"\x55\x20\x20\x20\x20\x20\x20\x20\x20\x20\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e"
    b"\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e"
    b"\x31\x2e\x31\x20\x00\x00\x2e\x01\x00\x00\x00\x30\x00\x00\x11\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31\x2e\x31"
    b"\x40\x00\x00\x11\x31\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30"
    b"\x38\x2e\x31\x2e\x32\x50\x00\x00\x5a\x51\x00\x00\x04\x00\x00\x3f"
    b"\xfe\x52\x00\x00\x20\x31\x2e\x32\x2e\x38\x32\x36\x2e\x30\x2e\x31"
    b"\x2e\x33\x36\x38\x30\x30\x34\x33\x2e\x39\x2e\x33\x38\x31\x31\x2e"
    b"\x30\x2e\x39\x2e\x30\x55\x00\x00\x0e\x50\x59\x4e\x45\x54\x44\x49"
    b"\x43\x4f\x4d\x5f\x30\x39\x30\x58\x00\x00\x10\x01\x01\x00\x0a\x70"
    b"\x79\x6e\x65\x74\x64\x69\x63\x6f\x6d\x00\x00\x53\x00\x00\x04\x00"
    b"\x05\x00\x05"
)

# A-ASSOCIATE-RQ with SCP/SCU Role Selection
A_ASSOCIATE_RQ_ROLE = (
    b"\x01\x00\x00\x00\x00\xfc\x00\x01\x00\x00\x41\x4e\x59\x2d\x53\x43"
    b"\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x47\x45\x54\x53\x43\x55"
    b"\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e"
    b"\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e"
    b"\x31\x2e\x31\x20\x00\x00\x38\x01\x00\x00\x00\x30\x00\x00\x19\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x35\x2e\x31"
    b"\x2e\x34\x2e\x31\x2e\x31\x2e\x32\x40\x00\x00\x13\x31\x2e\x32\x2e"
    b"\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31\x2e\x32\x2e\x31\x50"
    b"\x00\x00\x5f\x51\x00\x00\x04\x00\x00\x3f\xfe\x52\x00\x00\x20\x31"
    b"\x2e\x32\x2e\x38\x32\x36\x2e\x30\x2e\x31\x2e\x33\x36\x38\x30\x30"
    b"\x34\x33\x2e\x39\x2e\x33\x38\x31\x31\x2e\x30\x2e\x39\x2e\x30\x55"
    b"\x00\x00\x0e\x50\x59\x4e\x45\x54\x44\x49\x43\x4f\x4d\x5f\x30\x39"
    b"\x30\x54\x00\x00\x1d\x00\x19\x31\x2e\x32\x2e\x38\x34\x30\x2e\x31"
    b"\x30\x30\x30\x38\x2e\x35\x2e\x31\x2e\x34\x2e\x31\x2e\x31\x2e\x32"
    b"\x00\x01"
)

# A-ASSOCIATE-RQ with 3 contexts + user identity + async ops + ext negotiation
A_ASSOCIATE_RQ_EXT_NEG = (
    b"\x01\x00\x00\x00\x01\xab\x00\x01\x00\x00\x41\x4e\x59\x2d\x53\x43"
    b"\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x45\x43\x48\x4f\x53\x43"
    b"\x55\x20\x20\x20\x20\x20\x20\x20\x20\x20\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e"
    b"\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e"
    b"\x31\x2e\x31\x20\x00\x00\x2e\x01\x00\x00\x00\x30\x00\x00\x11\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31\x2e\x31"
    b"\x40\x00\x00\x11\x31\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30"
    b"\x38\x2e\x31\x2e\x32\x20\x00\x00\x36\x03\x00\x00\x00\x30\x00\x00"
    b"\x19\x31\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x35"
    b"\x2e\x31\x2e\x34\x2e\x31\x2e\x31\x2e\x32\x40\x00\x00\x11\x31\x2e"
    b"\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31\x2e\x32\x20"
    b"\x00\x00\x36\x05\x00\x00\x00\x30\x00\x00\x19\x31\x2e\x32\x2e\x38"
    b"\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x35\x2e\x31\x2e\x34\x2e\x31"
    b"\x2e\x31\x2e\x34\x40\x00\x00\x11\x31\x2e\x32\x2e\x38\x34\x30\x2e"
    b"\x31\x30\x30\x30\x38\x2e\x31\x2e\x32\x50\x00\x00\xa4\x51\x00\x00"
    b"\x04\x00\x00\x3f\xfe\x52\x00\x00\x20\x31\x2e\x32\x2e\x38\x32\x36"
    b"\x2e\x30\x2e\x31\x2e\x33\x36\x38\x30\x30\x34\x33\x2e\x39\x2e\x33"
    b"\x38\x31\x31\x2e\x30\x2e\x39\x2e\x30\x55\x00\x00\x0e\x50\x59\x4e"
    b"\x45\x54\x44\x49\x43\x4f\x4d\x5f\x30\x39\x30\x58\x00\x00\x10\x01"
    b"\x01\x00\x0a\x70\x79\x6e\x65\x74\x64\x69\x63\x6f\x6d\x00\x00\x53"
    b"\x00\x00\x04\x00\x05\x00\x05\x56\x00\x00\x21\x00\x19\x31\x2e\x32"
    b"\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x35\x2e\x31\x2e\x34"
    b"\x2e\x31\x2e\x31\x2e\x32\x02\x00\x03\x00\x01\x00\x56\x00\x00\x21"
    b"\x00\x19\x31\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e"
    b"\x35\x2e\x31\x2e\x34\x2e\x31\x2e\x31\x2e\x34\x02\x00\x03\x00\x01"
    b"\x00"
)

# A-ASSOCIATE-RQ with Called AET = 16 spaces (blank)
A_ASSOCIATE_RQ_CALLED_BLANK = (
    b"\x01\x00\x00\x00\x00\xd1\x00\x01\x00\x00"
    b"\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20"
    b"\x41\x4e\x59\x2d\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e\x32\x2e\x38\x34"
    b"\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e\x31\x2e"
    b"\x31\x20\x00\x00\x2e\x01\x00\x00\x00\x30\x00\x00\x11\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31"
    b"\x2e\x31\x40\x00\x00\x11\x31\x2e\x32\x2e\x38\x34\x30\x2e"
    b"\x31\x30\x30\x30\x38\x2e\x31\x2e\x32\x50\x00\x00\x3e\x51"
    b"\x00\x00\x04\x00\x00\x3f\xfe\x52\x00\x00\x20\x31\x2e\x32"
    b"\x2e\x38\x32\x36\x2e\x30\x2e\x31\x2e\x33\x36\x38\x30\x30"
    b"\x34\x33\x2e\x39\x2e\x33\x38\x31\x31\x2e\x30\x2e\x39\x2e"
    b"\x30\x55\x00\x00\x0e\x50\x59\x4e\x45\x54\x44\x49\x43\x4f"
    b"\x4d\x5f\x30\x39\x30"
)

# A-ASSOCIATE-RQ with Calling AET = 16 spaces (blank)
A_ASSOCIATE_RQ_CALLING_BLANK = (
    b"\x01\x00\x00\x00\x00\xd1\x00\x01\x00\x00"
    b"\x41\x4e\x59\x2d\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20"
    b"\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20\x20"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e\x32\x2e\x38\x34"
    b"\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e\x31\x2e"
    b"\x31\x20\x00\x00\x2e\x01\x00\x00\x00\x30\x00\x00\x11\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31"
    b"\x2e\x31\x40\x00\x00\x11\x31\x2e\x32\x2e\x38\x34\x30\x2e"
    b"\x31\x30\x30\x30\x38\x2e\x31\x2e\x32\x50\x00\x00\x3e\x51"
    b"\x00\x00\x04\x00\x00\x3f\xfe\x52\x00\x00\x20\x31\x2e\x32"
    b"\x2e\x38\x32\x36\x2e\x30\x2e\x31\x2e\x33\x36\x38\x30\x30"
    b"\x34\x33\x2e\x39\x2e\x33\x38\x31\x31\x2e\x30\x2e\x39\x2e"
    b"\x30\x55\x00\x00\x0e\x50\x59\x4e\x45\x54\x44\x49\x43\x4f"
    b"\x4d\x5f\x30\x39\x30"
)

# A-ASSOCIATE-RQ with username/password User Identity + 3 Transfer Syntaxes
# Has non-zero reserved byte (0xFF) in Pres Context — NOT suitable for round-trip
A_ASSOCIATE_RQ_USER_PASS = (
    b"\x01\x00\x00\x00\x01\x1f\x00\x01\x00\x00\x41\x4e\x59\x2d\x53\x43"
    b"\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x53\x54\x4f\x52\x45\x53"
    b"\x43\x55\x20\x20\x20\x20\x20\x20\x20\x20\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e"
    b"\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e"
    b"\x31\x2e\x31\x20\x00\x00\x64\x01\x00\xff\x00\x30\x00\x00\x19\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x35\x2e\x31"
    b"\x2e\x34\x2e\x31\x2e\x31\x2e\x32\x40\x00\x00\x13\x31\x2e\x32\x2e"
    b"\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31\x2e\x32\x2e\x31\x40"
    b"\x00\x00\x13\x31\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38"
    b"\x2e\x31\x2e\x32\x2e\x32\x40\x00\x00\x11\x31\x2e\x32\x2e\x38\x34"
    b"\x30\x2e\x31\x30\x30\x30\x38\x2e\x31\x2e\x32\x50\x00\x00\x56\x51"
    b"\x00\x00\x04\x00\x00\x40\x00\x52\x00\x00\x1b\x31\x2e\x32\x2e\x32"
    b"\x37\x36\x2e\x30\x2e\x37\x32\x33\x30\x30\x31\x30\x2e\x33\x2e\x30"
    b"\x2e\x33\x2e\x36\x2e\x30\x55\x00\x00\x0f\x4f\x46\x46\x49\x53\x5f"
    b"\x44\x43\x4d\x54\x4b\x5f\x33\x36\x30\x58\x00\x00\x18\x02\x00\x00"
    b"\x0a\x70\x79\x6e\x65\x74\x64\x69\x63\x6f\x6d\x00\x08\x70\x34\x73"
    b"\x73\x77\x30\x72\x64"
)

# A-ASSOCIATE-AC: basic
A_ASSOCIATE_AC_BASIC = (
    b"\x02\x00\x00\x00\x00\xb8\x00\x01\x00\x00\x41\x4e\x59\x2d"
    b"\x53\x43\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x45\x43"
    b"\x48\x4f\x53\x43\x55\x20\x20\x20\x20\x20\x20\x20\x20\x20"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e\x32\x2e\x38\x34"
    b"\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e\x31\x2e"
    b"\x31\x21\x00\x00\x19\x01\x00\x00\x00\x40\x00\x00\x11\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31"
    b"\x2e\x32\x50\x00\x00\x3a\x51\x00\x00\x04\x00\x00\x40\x00"
    b"\x52\x00\x00\x1b\x31\x2e\x32\x2e\x32\x37\x36\x2e\x30\x2e"
    b"\x37\x32\x33\x30\x30\x31\x30\x2e\x33\x2e\x30\x2e\x33\x2e"
    b"\x36\x2e\x30\x55\x00\x00\x0f\x4f\x46\x46\x49\x53\x5f\x44"
    b"\x43\x4d\x54\x4b\x5f\x33\x36\x30"
)

# A-ASSOCIATE-AC: one accepted (with TS), one rejected (TS sub-item present, zero-length)
A_ASSOCIATE_AC_ZERO_TS = (
    b"\x02\x00\x00\x00\x00\xb6\x00\x01\x00\x00\x41\x4e\x59\x2d\x53\x43"
    b"\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x50\x59\x4e\x45\x54\x44"
    b"\x49\x43\x4f\x4d\x20\x20\x20\x20\x20\x20\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e"
    b"\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e"
    b"\x31\x2e\x31\x21\x00\x00\x1b\x01\x00\x00\x00\x40\x00\x00\x13\x31"
    b"\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x31\x2e\x32"
    b"\x2e\x31\x21\x00\x00\x08\x03\x00\x03\x00\x40\x00\x00\x00\x50\x00"
    b"\x00\x2a\x51\x00\x00\x04\x00\x00\x70\x00\x52\x00\x00\x0a\x32\x2e"
    b"\x31\x36\x2e\x38\x34\x30\x2e\x31\x55\x00\x00\x10\x4d\x65\x72\x67"
    b"\x65\x43\x4f\x4d\x33\x5f\x33\x39\x30\x49\x42\x32"
)

# A-ASSOCIATE-AC: rejected context (no Transfer Syntax sub-item at all)
A_ASSOCIATE_AC_NO_TS = (
    b"\x02\x00\x00\x00\x00\xa7\x00\x01\x00\x00\x41\x4e\x59\x2d\x53\x43"
    b"\x50\x20\x20\x20\x20\x20\x20\x20\x20\x20\x50\x59\x4e\x45\x54\x44"
    b"\x49\x43\x4f\x4d\x20\x20\x20\x20\x20\x20\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x10\x00\x00\x15\x31\x2e"
    b"\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38\x2e\x33\x2e\x31\x2e"
    b"\x31\x2e\x31\x21\x00\x00\x04\x01\x00\x03\x00"
    b"\x50\x00\x00\x3e\x51\x00\x00\x04\x00\x00\x3f\xfe\x52\x00\x00\x20"
    b"\x31\x2e\x32\x2e\x38\x32\x36\x2e\x30\x2e\x31\x2e\x33\x36\x38\x30"
    b"\x30\x34\x33\x2e\x39\x2e\x33\x38\x31\x31\x2e\x31\x2e\x34\x2e\x30"
    b"\x55\x00\x00\x0e\x50\x59\x4e\x45\x54\x44\x49\x43\x4f\x4d\x5f\x31"
    b"\x34\x30"
)

# Simple PDUs
A_ASSOCIATE_RJ = b"\x03\x00\x00\x00\x00\x04\x00\x01\x01\x01"
A_RELEASE_RQ = b"\x05\x00\x00\x00\x00\x04\x00\x00\x00\x00"
A_RELEASE_RP = b"\x06\x00\x00\x00\x00\x04\x00\x00\x00\x00"
A_ABORT_USER = b"\x07\x00\x00\x00\x00\x04\x00\x00\x00\x00"
A_P_ABORT = b"\x07\x00\x00\x00\x00\x04\x00\x00\x02\x04"

# P-DATA-TF: C-ECHO-RSP (MCH=0x03: command + last)
P_DATA_TF = (
    b"\x04\x00\x00\x00\x00\x54\x00\x00\x00\x50\x01\x03\x00\x00\x00"
    b"\x00\x04\x00\x00\x00\x42\x00\x00\x00\x00\x00\x02\x00\x12\x00"
    b"\x00\x00\x31\x2e\x32\x2e\x38\x34\x30\x2e\x31\x30\x30\x30\x38"
    b"\x2e\x31\x2e\x31\x00\x00\x00\x00\x01\x02\x00\x00\x00\x30\x80"
    b"\x00\x00\x20\x01\x02\x00\x00\x00\x01\x00\x00\x00\x00\x08\x02"
    b"\x00\x00\x00\x01\x01\x00\x00\x00\x09\x02\x00\x00\x00\x00\x00"
)

# P-DATA-TF with MCH=0x02 (data, last fragment — NOT command)
# Single PDV: CID=1, MCH=0x02, data=\xaa\xbb
P_DATA_TF_DATA_LAST = (
    b"\x04\x00"                    # PDU type + reserved
    b"\x00\x00\x00\x08"            # PDU length = 8
    b"\x00\x00\x00\x04"            # PDV item length = 4 (CID + MCH + 2 bytes data)
    b"\x01"                        # Context ID = 1
    b"\x02"                        # MCH = 0x02: is_command=False, is_last=True
    b"\xaa\xbb"                    # data
)

# P-DATA-TF with MCH=0x01 (command, NOT last fragment)
P_DATA_TF_CMD_NOTLAST = (
    b"\x04\x00"                    # PDU type + reserved
    b"\x00\x00\x00\x08"            # PDU length = 8
    b"\x00\x00\x00\x04"            # PDV item length = 4
    b"\x03"                        # Context ID = 3
    b"\x01"                        # MCH = 0x01: is_command=True, is_last=False
    b"\xcc\xdd"                    # data
)


# ============================================================================
# Decode tests
# ============================================================================

class TestDecodeAssociateRQ:

    def test_basic_fields(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_BASIC)
        assert pdu['pdu_type'] == 0x01
        assert pdu['protocol_version'] == 1
        assert pdu['called_ae_title'] == 'ANY-SCP'
        assert pdu['calling_ae_title'] == 'ECHOSCU'
        assert pdu['application_context'] == '1.2.840.10008.3.1.1.1'

    def test_basic_presentation_context(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_BASIC)
        assert len(pdu['presentation_contexts']) == 1
        pc = pdu['presentation_contexts'][0]
        assert pc['id'] == 1
        assert pc['abstract_syntax'] == '1.2.840.10008.1.1'
        assert pc['transfer_syntaxes'] == ['1.2.840.10008.1.2']

    def test_basic_user_info(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_BASIC)
        ui = pdu['user_info']
        assert ui['max_pdu_length'] == 16382
        assert ui['implementation_class_uid'] == '1.2.826.0.1.3680043.9.3811.0.9.0'
        assert ui['implementation_version_name'] == 'PYNETDICOM_090'
        assert ui['role_selections'] == []
        assert ui['async_ops'] is None
        assert ui['user_identity'] is None
        assert ui['ext_negotiations'] == []

    def test_user_identity_username(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_USER_ASYNC)
        uid = pdu['user_info']['user_identity']
        assert uid is not None
        assert uid['type'] == 1
        assert uid['response_requested'] is True
        assert uid['primary'] == b'pynetdicom'
        assert uid['secondary'] == b''

    def test_async_ops_window(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_USER_ASYNC)
        ao = pdu['user_info']['async_ops']
        assert ao is not None
        assert ao['max_invoked'] == 5
        assert ao['max_performed'] == 5

    def test_role_selection(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_ROLE)
        assert pdu['calling_ae_title'] == 'GETSCU'
        rs = pdu['user_info']['role_selections']
        assert len(rs) == 1
        assert rs[0]['uid'] == '1.2.840.10008.5.1.4.1.1.2'
        assert rs[0]['scu'] is False
        assert rs[0]['scp'] is True

    def test_role_selection_presentation_context(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_ROLE)
        pc = pdu['presentation_contexts'][0]
        assert pc['id'] == 1
        assert pc['abstract_syntax'] == '1.2.840.10008.5.1.4.1.1.2'
        assert pc['transfer_syntaxes'] == ['1.2.840.10008.1.2.1']

    def test_multiple_contexts_and_ext_neg(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_EXT_NEG)
        assert len(pdu['presentation_contexts']) == 3
        assert pdu['presentation_contexts'][0]['id'] == 1
        assert pdu['presentation_contexts'][1]['id'] == 3
        assert pdu['presentation_contexts'][2]['id'] == 5
        assert pdu['presentation_contexts'][1]['abstract_syntax'] == '1.2.840.10008.5.1.4.1.1.2'
        assert pdu['presentation_contexts'][2]['abstract_syntax'] == '1.2.840.10008.5.1.4.1.1.4'

    def test_ext_negotiations(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_EXT_NEG)
        en = pdu['user_info']['ext_negotiations']
        assert len(en) == 2
        assert en[0]['uid'] == '1.2.840.10008.5.1.4.1.1.2'
        assert en[0]['app_info'] == b'\x02\x00\x03\x00\x01\x00'
        assert en[1]['uid'] == '1.2.840.10008.5.1.4.1.1.4'

    def test_blank_called_ae(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_CALLED_BLANK)
        assert pdu['called_ae_title'] == ''
        assert pdu['calling_ae_title'] == 'ANY-'

    def test_blank_calling_ae(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_CALLING_BLANK)
        assert pdu['called_ae_title'] == 'ANY-'
        assert pdu['calling_ae_title'] == ''

    def test_user_identity_user_pass(self):
        pdu = decode_pdu(A_ASSOCIATE_RQ_USER_PASS)
        assert pdu['calling_ae_title'] == 'STORESCU'
        pc = pdu['presentation_contexts'][0]
        assert len(pc['transfer_syntaxes']) == 3
        ui = pdu['user_info']
        assert ui['max_pdu_length'] == 16384
        assert ui['implementation_class_uid'] == '1.2.276.0.7230010.3.0.3.6.0'
        assert ui['implementation_version_name'] == 'OFFIS_DCMTK_360'
        uid = ui['user_identity']
        assert uid['type'] == 2
        assert uid['response_requested'] is False
        assert uid['primary'] == b'pynetdicom'
        assert uid['secondary'] == b'p4ssw0rd'


class TestDecodeAssociateAC:

    def test_basic_ac(self):
        pdu = decode_pdu(A_ASSOCIATE_AC_BASIC)
        assert pdu['pdu_type'] == 0x02
        assert pdu['called_ae_title'] == 'ANY-SCP'
        assert pdu['calling_ae_title'] == 'ECHOSCU'
        pc = pdu['presentation_contexts'][0]
        assert pc['id'] == 1
        assert pc['result'] == 0
        assert pc['transfer_syntax'] == '1.2.840.10008.1.2'
        ui = pdu['user_info']
        assert ui['max_pdu_length'] == 16384
        assert ui['implementation_class_uid'] == '1.2.276.0.7230010.3.0.3.6.0'
        assert ui['implementation_version_name'] == 'OFFIS_DCMTK_360'

    def test_ac_zero_ts(self):
        pdu = decode_pdu(A_ASSOCIATE_AC_ZERO_TS)
        assert len(pdu['presentation_contexts']) == 2
        pc1 = pdu['presentation_contexts'][0]
        assert pc1['result'] == 0
        assert pc1['transfer_syntax'] == '1.2.840.10008.1.2.1'
        pc2 = pdu['presentation_contexts'][1]
        assert pc2['id'] == 3
        assert pc2['result'] == 3
        assert pc2['transfer_syntax'] == ''

    def test_ac_no_ts(self):
        pdu = decode_pdu(A_ASSOCIATE_AC_NO_TS)
        pc = pdu['presentation_contexts'][0]
        assert pc['id'] == 1
        assert pc['result'] == 3
        assert pc['transfer_syntax'] is None
        ui = pdu['user_info']
        assert ui['max_pdu_length'] == 16382
        assert ui['implementation_class_uid'] == '1.2.826.0.1.3680043.9.3811.1.4.0'
        assert ui['implementation_version_name'] == 'PYNETDICOM_140'


class TestDecodeSimplePDUs:

    def test_associate_rj(self):
        pdu = decode_pdu(A_ASSOCIATE_RJ)
        assert pdu['pdu_type'] == 0x03
        assert pdu['result'] == 1
        assert pdu['source'] == 1
        assert pdu['reason'] == 1

    def test_release_rq(self):
        assert decode_pdu(A_RELEASE_RQ)['pdu_type'] == 0x05

    def test_release_rp(self):
        assert decode_pdu(A_RELEASE_RP)['pdu_type'] == 0x06

    def test_abort_user(self):
        pdu = decode_pdu(A_ABORT_USER)
        assert pdu['pdu_type'] == 0x07
        assert pdu['source'] == 0
        assert pdu['reason'] == 0

    def test_abort_provider(self):
        pdu = decode_pdu(A_P_ABORT)
        assert pdu['source'] == 2
        assert pdu['reason'] == 4


class TestDecodePDataTF:

    def test_pdata_basic(self):
        pdu = decode_pdu(P_DATA_TF)
        assert pdu['pdu_type'] == 0x04
        assert len(pdu['pdvs']) == 1
        pdv = pdu['pdvs'][0]
        assert pdv['context_id'] == 1
        assert pdv['is_command'] is True
        assert pdv['is_last'] is True
        assert len(pdv['data']) == 78

    def test_pdata_data_last_fragment(self):
        """MCH=0x02: data set (not command), last fragment."""
        pdu = decode_pdu(P_DATA_TF_DATA_LAST)
        pdv = pdu['pdvs'][0]
        assert pdv['context_id'] == 1
        assert pdv['is_command'] is False
        assert pdv['is_last'] is True
        assert pdv['data'] == b'\xaa\xbb'

    def test_pdata_command_not_last(self):
        """MCH=0x01: command set, NOT last fragment."""
        pdu = decode_pdu(P_DATA_TF_CMD_NOTLAST)
        pdv = pdu['pdvs'][0]
        assert pdv['context_id'] == 3
        assert pdv['is_command'] is True
        assert pdv['is_last'] is False
        assert pdv['data'] == b'\xcc\xdd'


# ============================================================================
# Round-trip tests
# ============================================================================

class TestRoundTrip:

    @pytest.mark.parametrize("name,data", [
        ("rq_basic", A_ASSOCIATE_RQ_BASIC),
        ("rq_user_async", A_ASSOCIATE_RQ_USER_ASYNC),
        ("rq_role", A_ASSOCIATE_RQ_ROLE),
        ("rq_ext_neg", A_ASSOCIATE_RQ_EXT_NEG),
        ("rq_called_blank", A_ASSOCIATE_RQ_CALLED_BLANK),
        ("rq_calling_blank", A_ASSOCIATE_RQ_CALLING_BLANK),
        ("ac_basic", A_ASSOCIATE_AC_BASIC),
        ("ac_zero_ts", A_ASSOCIATE_AC_ZERO_TS),
        ("ac_no_ts", A_ASSOCIATE_AC_NO_TS),
        ("rj", A_ASSOCIATE_RJ),
        ("release_rq", A_RELEASE_RQ),
        ("release_rp", A_RELEASE_RP),
        ("abort_user", A_ABORT_USER),
        ("abort_provider", A_P_ABORT),
        ("pdata", P_DATA_TF),
        ("pdata_data_last", P_DATA_TF_DATA_LAST),
        ("pdata_cmd_notlast", P_DATA_TF_CMD_NOTLAST),
    ])
    def test_round_trip(self, name, data):
        decoded = decode_pdu(data)
        re_encoded = encode_pdu(decoded)
        assert re_encoded == data, (
            f"Round-trip failed for {name}: "
            f"expected {len(data)} bytes, got {len(re_encoded)} bytes"
        )


# ============================================================================
# Encoding from dicts
# ============================================================================

class TestEncodeFromDict:

    def test_encode_release_rq(self):
        assert encode_pdu({'pdu_type': 0x05}) == A_RELEASE_RQ

    def test_encode_release_rp(self):
        assert encode_pdu({'pdu_type': 0x06}) == A_RELEASE_RP

    def test_encode_abort(self):
        pdu = {'pdu_type': 0x07, 'source': 2, 'reason': 4}
        assert encode_pdu(pdu) == A_P_ABORT

    def test_encode_associate_rj(self):
        pdu = {'pdu_type': 0x03, 'result': 1, 'source': 1, 'reason': 1}
        assert encode_pdu(pdu) == A_ASSOCIATE_RJ

    def test_encode_pdata_single_pdv(self):
        pdu = {
            'pdu_type': 0x04,
            'pdvs': [
                {'context_id': 1, 'is_command': True, 'is_last': True,
                 'data': b'\xaa\xbb'},
            ]
        }
        encoded = encode_pdu(pdu)
        assert len(encoded) == 14
        assert encoded[0] == 0x04
        pdv_len = struct.unpack('>I', encoded[6:10])[0]
        assert pdv_len == 4
        assert encoded[10] == 1
        assert encoded[11] == 0x03  # MCH: command + last
        assert encoded[12:14] == b'\xaa\xbb'

    def test_encode_minimal_associate_rq(self):
        pdu = {
            'pdu_type': 0x01,
            'protocol_version': 1,
            'called_ae_title': 'SCP',
            'calling_ae_title': 'SCU',
            'application_context': '1.2.840.10008.3.1.1.1',
            'presentation_contexts': [
                {'id': 1, 'abstract_syntax': '1.2.840.10008.1.1',
                 'transfer_syntaxes': ['1.2.840.10008.1.2']}
            ],
            'user_info': {
                'max_pdu_length': 16384,
                'implementation_class_uid': '1.2.3.4',
                'implementation_version_name': 'TEST',
                'role_selections': [],
                'async_ops': None,
                'user_identity': None,
                'ext_negotiations': [],
            }
        }
        encoded = encode_pdu(pdu)
        decoded = decode_pdu(encoded)
        assert decoded['called_ae_title'] == 'SCP'
        assert decoded['calling_ae_title'] == 'SCU'
        assert decoded['user_info']['max_pdu_length'] == 16384
        assert decoded['user_info']['implementation_version_name'] == 'TEST'
        # Double round-trip
        assert encode_pdu(decoded) == encoded


# ============================================================================
# SCP/SCU Role Selection Negotiation
# ============================================================================

DEFAULT_ROLE = (True, False, False, True)
BOTH_SCU_SCP_ROLE = (True, True, True, True)
CONTEXT_REJECTED = (False, False, False, False)
INVERTED_ROLE = (False, True, True, False)

ROLE_TEST_CASES = [
    (None, None, None, None, DEFAULT_ROLE),
    (None, None, None, True, DEFAULT_ROLE),
    (None, None, None, False, DEFAULT_ROLE),
    (None, None, True, None, DEFAULT_ROLE),
    (None, None, False, None, DEFAULT_ROLE),
    (None, None, True, True, DEFAULT_ROLE),
    (None, None, True, False, DEFAULT_ROLE),
    (None, None, False, False, DEFAULT_ROLE),
    (None, None, False, True, DEFAULT_ROLE),
    (True, True, None, None, DEFAULT_ROLE),
    (True, True, None, True, DEFAULT_ROLE),
    (True, True, None, False, DEFAULT_ROLE),
    (True, True, True, None, DEFAULT_ROLE),
    (True, True, False, None, DEFAULT_ROLE),
    (True, True, True, True, BOTH_SCU_SCP_ROLE),
    (True, True, True, False, DEFAULT_ROLE),
    (True, True, False, False, CONTEXT_REJECTED),
    (True, True, False, True, INVERTED_ROLE),
    (True, False, None, None, DEFAULT_ROLE),
    (True, False, None, True, DEFAULT_ROLE),
    (True, False, None, False, DEFAULT_ROLE),
    (True, False, True, None, DEFAULT_ROLE),
    (True, False, False, None, DEFAULT_ROLE),
    (True, False, True, True, DEFAULT_ROLE),
    (True, False, True, False, DEFAULT_ROLE),
    (True, False, False, False, CONTEXT_REJECTED),
    (True, False, False, True, CONTEXT_REJECTED),
    (False, True, None, None, DEFAULT_ROLE),
    (False, True, None, True, DEFAULT_ROLE),
    (False, True, None, False, DEFAULT_ROLE),
    (False, True, True, None, DEFAULT_ROLE),
    (False, True, False, None, DEFAULT_ROLE),
    (False, True, True, True, INVERTED_ROLE),
    (False, True, True, False, CONTEXT_REJECTED),
    (False, True, False, False, CONTEXT_REJECTED),
    (False, True, False, True, INVERTED_ROLE),
    (False, False, None, None, DEFAULT_ROLE),
    (False, False, None, True, DEFAULT_ROLE),
    (False, False, None, False, DEFAULT_ROLE),
    (False, False, True, None, DEFAULT_ROLE),
    (False, False, False, None, DEFAULT_ROLE),
    (False, False, True, True, CONTEXT_REJECTED),
    (False, False, True, False, CONTEXT_REJECTED),
    (False, False, False, False, CONTEXT_REJECTED),
    (False, False, False, True, CONTEXT_REJECTED),
]


class TestNegotiateRoles:

    @pytest.mark.parametrize(
        "req_scu,req_scp,acc_scu,acc_scp,expected",
        ROLE_TEST_CASES,
        ids=[f"req({r[0]},{r[1]})-acc({r[2]},{r[3]})" for r in ROLE_TEST_CASES]
    )
    def test_role_negotiation(self, req_scu, req_scp, acc_scu, acc_scp, expected):
        result = negotiate_roles(req_scu, req_scp, acc_scu, acc_scp)
        assert result == expected


# ============================================================================
# Fragmentation
# ============================================================================

class TestFragmentation:

    def test_no_fragmentation_unlimited(self):
        pdvs = [{'context_id': 1, 'is_command': True, 'is_last': True,
                 'data': b'\x00' * 100}]
        result = fragment_pdata(pdvs, 0)
        assert len(result) == 1
        decoded = decode_pdu(result[0])
        assert decoded['pdvs'][0]['data'] == b'\x00' * 100
        assert decoded['pdvs'][0]['is_last'] is True

    def test_fragmentation_splits_large_pdv(self):
        original_data = bytes(range(256)) * 4  # 1024 bytes
        pdvs = [{'context_id': 3, 'is_command': False, 'is_last': True,
                 'data': original_data}]
        result = fragment_pdata(pdvs, 100)
        assert len(result) > 1
        reassembled = b''
        for i, pdu_bytes in enumerate(result):
            assert len(pdu_bytes) <= 100
            decoded = decode_pdu(pdu_bytes)
            pdv = decoded['pdvs'][0]
            assert pdv['context_id'] == 3
            assert pdv['is_command'] is False
            reassembled += pdv['data']
            if i < len(result) - 1:
                assert pdv['is_last'] is False
            else:
                assert pdv['is_last'] is True
        assert reassembled == original_data

    def test_fragmentation_small_data_no_split(self):
        pdvs = [{'context_id': 1, 'is_command': True, 'is_last': True,
                 'data': b'\xab' * 10}]
        result = fragment_pdata(pdvs, 100)
        assert len(result) == 1
        decoded = decode_pdu(result[0])
        assert decoded['pdvs'][0]['data'] == b'\xab' * 10

    def test_fragmentation_multiple_pdvs(self):
        pdvs = [
            {'context_id': 1, 'is_command': True, 'is_last': True,
             'data': b'\x01' * 20},
            {'context_id': 1, 'is_command': False, 'is_last': True,
             'data': b'\x02' * 20},
        ]
        result = fragment_pdata(pdvs, 50)
        assert len(result) == 2
        d1 = decode_pdu(result[0])
        assert d1['pdvs'][0]['data'] == b'\x01' * 20
        assert d1['pdvs'][0]['is_command'] is True
        d2 = decode_pdu(result[1])
        assert d2['pdvs'][0]['data'] == b'\x02' * 20
        assert d2['pdvs'][0]['is_command'] is False

    def test_pdata_round_trip_with_fragment(self):
        data = b'\xde\xad\xbe\xef' * 50  # 200 bytes
        pdvs = [{'context_id': 5, 'is_command': True, 'is_last': True,
                 'data': data}]
        fragments = fragment_pdata(pdvs, 60)
        assert len(fragments) >= 4
        reassembled = b''
        for frag in fragments:
            decoded = decode_pdu(frag)
            reassembled += decoded['pdvs'][0]['data']
        assert reassembled == data


# ============================================================================
# Stream analysis
# ============================================================================

@pytest.fixture(scope='session')
def capture_dir():
    """Create binary capture files for stream analysis testing."""
    capdir = '/app/captures'
    os.makedirs(capdir, exist_ok=True)

    # --- Raw framing: echo exchange ---
    with open(os.path.join(capdir, 'raw_exchange.bin'), 'wb') as f:
        f.write(A_ASSOCIATE_RQ_BASIC)
        f.write(A_ASSOCIATE_AC_BASIC)
        f.write(P_DATA_TF)
        f.write(A_RELEASE_RQ)
        f.write(A_RELEASE_RP)

    # --- Timestamped framing ---
    with open(os.path.join(capdir, 'timed_exchange.bin'), 'wb') as f:
        ts_base = 1700000000
        for i, pdu_bytes in enumerate([A_RELEASE_RQ, A_RELEASE_RP, A_P_ABORT]):
            f.write(struct.pack('>II', ts_base + i, len(pdu_bytes)))
            f.write(pdu_bytes)

    # --- Raw framing with violations ---
    release_bad = bytearray(A_RELEASE_RQ)
    release_bad[1] = 0xFF  # Non-zero reserved byte
    with open(os.path.join(capdir, 'violations.bin'), 'wb') as f:
        f.write(bytes(release_bad))
        f.write(A_RELEASE_RP)

    # --- Raw framing with UID too long ---
    long_uid = '1.' + '2' * 70  # 72 chars > 64
    long_uid_bytes = long_uid.encode('ascii')
    ac_item = struct.pack('>BxH', 0x10, len(long_uid_bytes)) + long_uid_bytes
    as_bytes = b'1.2.840.10008.1.1'
    ts_bytes = b'1.2.840.10008.1.2'
    pc_sub = struct.pack('>BxH', 0x30, len(as_bytes)) + as_bytes
    pc_sub += struct.pack('>BxH', 0x40, len(ts_bytes)) + ts_bytes
    pc_body = struct.pack('>Bxxx', 1) + pc_sub
    pc_item = struct.pack('>BxH', 0x20, len(pc_body)) + pc_body
    ui_sub = struct.pack('>BxHI', 0x51, 4, 16384)
    ic_bytes = b'1.2.3.4'
    ui_sub += struct.pack('>BxH', 0x52, len(ic_bytes)) + ic_bytes
    ui_item = struct.pack('>BxH', 0x50, len(ui_sub)) + ui_sub
    items = ac_item + pc_item + ui_item
    body = struct.pack('>Hxx', 1)
    body += b'LONGSCP         '
    body += b'LONGSCU         '
    body += b'\x00' * 32 + items
    long_uid_pdu = struct.pack('>BxI', 0x01, len(body)) + body
    with open(os.path.join(capdir, 'long_uid.bin'), 'wb') as f:
        f.write(long_uid_pdu)

    # --- PCAP: echo exchange (each PDU in a single TCP segment) ---
    pcap_exchange = [
        ('c2s', A_ASSOCIATE_RQ_BASIC),
        ('s2c', A_ASSOCIATE_AC_BASIC),
        ('c2s', P_DATA_TF),
        ('c2s', A_RELEASE_RQ),
        ('s2c', A_RELEASE_RP),
    ]
    with open(os.path.join(capdir, 'echo_exchange.pcap'), 'wb') as f:
        f.write(build_dicom_pcap(pcap_exchange))

    # --- PCAP: echo exchange with first PDU split across TCP segments ---
    with open(os.path.join(capdir, 'echo_split.pcap'), 'wb') as f:
        f.write(build_dicom_pcap(pcap_exchange, split_first=True))

    return capdir


class TestAnalyzeStreamRawFraming:

    def test_raw_exchange_framing(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'raw_exchange.bin'))
        assert result['framing'] == 'raw'
        assert result['pdu_count'] == 5

    def test_raw_exchange_pdu_types(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'raw_exchange.bin'))
        types = [p['pdu_type'] for p in result['pdus']]
        assert types == [0x01, 0x02, 0x04, 0x05, 0x06]

    def test_raw_exchange_type_names(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'raw_exchange.bin'))
        names = [p['pdu_type_name'] for p in result['pdus']]
        assert names == [
            'A-ASSOCIATE-RQ', 'A-ASSOCIATE-AC', 'P-DATA-TF',
            'A-RELEASE-RQ', 'A-RELEASE-RP',
        ]

    def test_raw_exchange_offsets(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'raw_exchange.bin'))
        offsets = [p['offset'] for p in result['pdus']]
        assert offsets[0] == 0
        rq_len = 6 + struct.unpack('>I', A_ASSOCIATE_RQ_BASIC[2:6])[0]
        assert offsets[1] == rq_len
        ac_len = 6 + struct.unpack('>I', A_ASSOCIATE_AC_BASIC[2:6])[0]
        assert offsets[2] == rq_len + ac_len

    def test_raw_exchange_no_violations(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'raw_exchange.bin'))
        for p in result['pdus']:
            assert p['violations'] == []
        assert result['violation_summary']['NONZERO_RESERVED'] == 0

    def test_raw_exchange_timestamps_null(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'raw_exchange.bin'))
        for p in result['pdus']:
            assert p['timestamp'] is None

    def test_raw_decoded_fields(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'raw_exchange.bin'))
        rq = result['pdus'][0]['decoded']
        assert rq['called_ae_title'] == 'ANY-SCP'
        assert rq['calling_ae_title'] == 'ECHOSCU'


class TestAnalyzeStreamTimestampedFraming:

    def test_timestamped_framing(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'timed_exchange.bin'))
        assert result['framing'] == 'timestamped'
        assert result['pdu_count'] == 3

    def test_timestamped_types(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'timed_exchange.bin'))
        types = [p['pdu_type'] for p in result['pdus']]
        assert types == [0x05, 0x06, 0x07]

    def test_timestamped_timestamps(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'timed_exchange.bin'))
        ts = [p['timestamp'] for p in result['pdus']]
        assert ts == [1700000000.0, 1700000001.0, 1700000002.0]

    def test_timestamped_offsets(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'timed_exchange.bin'))
        assert result['pdus'][0]['offset'] == 8
        assert result['pdus'][1]['offset'] == 26
        assert result['pdus'][2]['offset'] == 44


class TestAnalyzeStreamViolations:

    def test_nonzero_reserved_detected(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'violations.bin'))
        assert result['pdu_count'] == 2
        assert 'NONZERO_RESERVED' in result['pdus'][0]['violations']
        assert result['pdus'][1]['violations'] == []
        assert result['violation_summary']['NONZERO_RESERVED'] == 1

    def test_uid_too_long_detected(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'long_uid.bin'))
        assert result['pdu_count'] == 1
        assert 'UID_TOO_LONG' in result['pdus'][0]['violations']
        assert result['violation_summary']['UID_TOO_LONG'] >= 1


# ============================================================================
# PCAP stream analysis (requires tshark for TCP reassembly)
# ============================================================================

class TestAnalyzeStreamPCAP:

    def test_pcap_framing_detected(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'echo_exchange.pcap'))
        assert result['framing'] == 'pcap'

    def test_pcap_pdu_count(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'echo_exchange.pcap'))
        assert result['pdu_count'] == 5

    def test_pcap_pdu_types(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'echo_exchange.pcap'))
        types = [p['pdu_type'] for p in result['pdus']]
        assert types == [0x01, 0x02, 0x04, 0x05, 0x06]

    def test_pcap_type_names(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'echo_exchange.pcap'))
        names = [p['pdu_type_name'] for p in result['pdus']]
        assert names == [
            'A-ASSOCIATE-RQ', 'A-ASSOCIATE-AC', 'P-DATA-TF',
            'A-RELEASE-RQ', 'A-RELEASE-RP',
        ]

    def test_pcap_decoded_fields(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'echo_exchange.pcap'))
        rq = result['pdus'][0]['decoded']
        assert rq['called_ae_title'] == 'ANY-SCP'
        assert rq['calling_ae_title'] == 'ECHOSCU'
        ac = result['pdus'][1]['decoded']
        assert ac['pdu_type'] == 0x02
        assert ac['user_info']['implementation_version_name'] == 'OFFIS_DCMTK_360'

    def test_pcap_no_violations(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'echo_exchange.pcap'))
        for p in result['pdus']:
            assert p['violations'] == []
        assert result['violation_summary']['NONZERO_RESERVED'] == 0

    def test_pcap_tcp_reassembly(self, capture_dir):
        """PCAP with a PDU split across TCP segments must be reassembled."""
        result = analyze_stream(os.path.join(capture_dir, 'echo_split.pcap'))
        assert result['framing'] == 'pcap'
        assert result['pdu_count'] == 5
        rq = result['pdus'][0]['decoded']
        assert rq['called_ae_title'] == 'ANY-SCP'
        assert rq['calling_ae_title'] == 'ECHOSCU'
        assert rq['user_info']['max_pdu_length'] == 16382

    def test_pcap_violation_summary_structure(self, capture_dir):
        result = analyze_stream(os.path.join(capture_dir, 'echo_exchange.pcap'))
        assert 'violation_summary' in result
        assert 'NONZERO_RESERVED' in result['violation_summary']
        assert 'UID_TOO_LONG' in result['violation_summary']


# ============================================================================
# CLI
# ============================================================================

class TestCLI:

    def test_cli_json_output(self, capture_dir):
        proc = subprocess.run(
            ['python3', '/app/dicom_codec.py',
             os.path.join(capture_dir, 'raw_exchange.bin')],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data['framing'] == 'raw'
        assert data['pdu_count'] == 5
        assert len(data['pdus']) == 5

    def test_cli_timestamped(self, capture_dir):
        proc = subprocess.run(
            ['python3', '/app/dicom_codec.py',
             os.path.join(capture_dir, 'timed_exchange.bin')],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data['framing'] == 'timestamped'
        assert data['pdus'][0]['timestamp'] == 1700000000.0

    def test_cli_pcap(self, capture_dir):
        proc = subprocess.run(
            ['python3', '/app/dicom_codec.py',
             os.path.join(capture_dir, 'echo_exchange.pcap')],
            capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data['framing'] == 'pcap'
        assert data['pdu_count'] == 5
        assert data['pdus'][0]['pdu_type_name'] == 'A-ASSOCIATE-RQ'
