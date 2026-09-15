
"""
Verify that:
1. /app/opcodes.json documents the VM instruction set with correct sizes
2. /app/config_dump.txt contains the correct decrypted firmware configuration
3. /app/emulator.py faithfully reproduces the VM's behavior
4. /app/payload.bin produces the correct output when run through the emulator
"""

import hashlib
import json
import os
import subprocess
import pytest


CONFIG_PATH = "/app/config_dump.txt"
OPCODES_PATH = "/app/opcodes.json"
EMULATOR_PATH = "/app/emulator.py"
PAYLOAD_PATH = "/app/payload.bin"
FIRMWARE_PATH = "/app/firmware"

# SHA-256 hashes of each expected config line
EXPECTED_LINE_HASHES = [
    "72d1d1d551519e1bc4e50bdce2d1c1e8370374ddb08b963f2a37853cfbfa1c54",
    "389c22494ffaab0cf001f159a3c2b72cf142e7a9466d55090deabe9ed650fb8f",
    "960e4acefd06e7c76a7153354ae77b4ad010d544df4567a2031416075fda90a6",
    "ee035608175deffab973665735cc49cd1aa647c0e4170acaab933c7e7c5bcf4b",
]

# SHA-256 of all 4 lines joined by "\n"
EXPECTED_FULL_HASH = "f4a511bc05fe05149e93b127fdd26ab25727dfe789f58c00ccfb308e1160473f"

# Expected instruction sizes for opcodes used in the bytecode
# Maps normalized opcode int -> total instruction size in bytes
EXPECTED_OPCODE_SIZES = {
    0x10: 3,   # LDI rX, imm8
    0x20: 3,   # XOR rX, rY
    0x40: 3,   # ADDI rX, imm8
    0x60: 2,   # OUT rX
    0x70: 2,   # NOT rX
    0x80: 2,   # DEC rX
    0x90: 2,   # JNZ off8
    0xA0: 3,   # LDTBL rX, rY
    0xFF: 1,   # HLT
}

# Additional opcodes in the interpreter but not in bytecode
EXTRA_OPCODE_SIZES = {
    0x30: 3,   # ADD rX, rY
    0x50: 3,   # MOV rX, rY
}

PAYLOAD_TARGET = "ANALYSIS_PASS"
PAYLOAD_MAX_SIZE = 64


def normalize_opcode_key(key_str):
    """Convert various opcode key formats to an integer."""
    key_str = key_str.strip().lower()
    if key_str.startswith("0x"):
        return int(key_str, 16)
    try:
        return int(key_str)
    except ValueError:
        return None


def read_config():
    """Read and normalize the config dump file."""
    assert os.path.isfile(CONFIG_PATH), (
        f"{CONFIG_PATH} does not exist. "
        "The agent must write decrypted config entries to this file."
    )
    with open(CONFIG_PATH, "r") as f:
        content = f.read().strip()
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    return lines


class TestOpcodes:
    def test_opcodes_file_exists(self):
        assert os.path.isfile(OPCODES_PATH), f"{OPCODES_PATH} not found"

    def test_opcodes_valid_json(self):
        with open(OPCODES_PATH, "r") as f:
            data = json.load(f)
        assert isinstance(data, dict), "opcodes.json must be a JSON object"

    def test_opcodes_has_bytecode_opcodes(self):
        """All opcodes used in the bytecode must be documented."""
        with open(OPCODES_PATH, "r") as f:
            data = json.load(f)

        documented = set()
        for key in data:
            val = normalize_opcode_key(key)
            if val is not None:
                documented.add(val)

        for opcode in EXPECTED_OPCODE_SIZES:
            assert opcode in documented, (
                f"Opcode 0x{opcode:02X} is used in the bytecode but not "
                f"documented in opcodes.json"
            )

    def test_opcodes_correct_sizes(self):
        """Instruction sizes must be correct for all documented bytecode opcodes."""
        with open(OPCODES_PATH, "r") as f:
            data = json.load(f)

        opcode_map = {}
        for key, val in data.items():
            norm = normalize_opcode_key(key)
            if norm is not None:
                opcode_map[norm] = val

        for opcode, expected_size in EXPECTED_OPCODE_SIZES.items():
            assert opcode in opcode_map, (
                f"Opcode 0x{opcode:02X} not found in opcodes.json"
            )
            entry = opcode_map[opcode]
            assert isinstance(entry, dict), (
                f"Entry for 0x{opcode:02X} must be a JSON object"
            )
            assert "size" in entry, (
                f"Entry for 0x{opcode:02X} must have a 'size' field"
            )
            assert entry["size"] == expected_size, (
                f"Opcode 0x{opcode:02X}: expected size {expected_size}, "
                f"got {entry['size']}"
            )

    def test_opcodes_has_descriptions(self):
        """Each documented opcode must have a description."""
        with open(OPCODES_PATH, "r") as f:
            data = json.load(f)

        for key, val in data.items():
            norm = normalize_opcode_key(key)
            if norm is not None and norm in EXPECTED_OPCODE_SIZES:
                assert isinstance(val, dict), (
                    f"Entry for {key} must be a JSON object"
                )
                assert "description" in val and len(str(val["description"])) > 0, (
                    f"Entry for {key} must have a non-empty 'description' field"
                )

    def test_opcodes_has_extra_opcodes(self):
        """Opcodes present in the interpreter but not in bytecode must also be documented."""
        with open(OPCODES_PATH, "r") as f:
            data = json.load(f)

        opcode_map = {}
        for key, val in data.items():
            norm = normalize_opcode_key(key)
            if norm is not None:
                opcode_map[norm] = val

        for opcode, expected_size in EXTRA_OPCODE_SIZES.items():
            assert opcode in opcode_map, (
                f"Opcode 0x{opcode:02X} is in the interpreter but not "
                f"documented in opcodes.json"
            )
            entry = opcode_map[opcode]
            assert isinstance(entry, dict) and "size" in entry, (
                f"Entry for 0x{opcode:02X} must be a JSON object with 'size'"
            )
            assert entry["size"] == expected_size, (
                f"Opcode 0x{opcode:02X}: expected size {expected_size}, "
                f"got {entry['size']}"
            )


class TestConfigDump:
    def test_file_exists(self):
        assert os.path.isfile(CONFIG_PATH), f"{CONFIG_PATH} not found"

    def test_has_four_entries(self):
        lines = read_config()
        assert len(lines) == 4, (
            f"Expected 4 config entries, got {len(lines)}"
        )

    def test_all_entries_are_key_value(self):
        lines = read_config()
        for i, line in enumerate(lines):
            assert "=" in line, (
                f"Line {i+1} is not in KEY=VALUE format: {line!r}"
            )

    def test_entry_1_correct(self):
        lines = read_config()
        h = hashlib.sha256(lines[0].encode()).hexdigest()
        assert h == EXPECTED_LINE_HASHES[0], "Entry 1 (first config line) is incorrect"

    def test_entry_2_correct(self):
        lines = read_config()
        h = hashlib.sha256(lines[1].encode()).hexdigest()
        assert h == EXPECTED_LINE_HASHES[1], "Entry 2 (second config line) is incorrect"

    def test_entry_3_correct(self):
        lines = read_config()
        h = hashlib.sha256(lines[2].encode()).hexdigest()
        assert h == EXPECTED_LINE_HASHES[2], "Entry 3 (third config line) is incorrect"

    def test_entry_4_correct(self):
        lines = read_config()
        h = hashlib.sha256(lines[3].encode()).hexdigest()
        assert h == EXPECTED_LINE_HASHES[3], "Entry 4 (fourth config line) is incorrect"

    def test_full_content_hash(self):
        lines = read_config()
        full = "\n".join(lines)
        h = hashlib.sha256(full.encode()).hexdigest()
        assert h == EXPECTED_FULL_HASH, (
            "Complete config dump content does not match expected hash"
        )


class TestEmulator:
    """Verify the standalone emulator faithfully reproduces the binary's VM."""

    def test_emulator_exists(self):
        assert os.path.isfile(EMULATOR_PATH), f"{EMULATOR_PATH} not found"

    def test_emulator_reproduces_config(self):
        """Running emulator on original bytecode+data must produce the correct config."""
        # Extract original VM sections from the stripped binary
        vmcode_tmp = "/tmp/test_vmcode.bin"
        vmdata_tmp = "/tmp/test_vmdata.bin"

        r1 = subprocess.run(
            ["objcopy", "-O", "binary", "--only-section=.vmcode",
             FIRMWARE_PATH, vmcode_tmp],
            capture_output=True, text=True
        )
        assert r1.returncode == 0, f"Failed to extract .vmcode: {r1.stderr}"

        r2 = subprocess.run(
            ["objcopy", "-O", "binary", "--only-section=.vmdata",
             FIRMWARE_PATH, vmdata_tmp],
            capture_output=True, text=True
        )
        assert r2.returncode == 0, f"Failed to extract .vmdata: {r2.stderr}"

        # Run the emulator on the original sections
        result = subprocess.run(
            ["python3", EMULATOR_PATH, vmcode_tmp, vmdata_tmp],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"Emulator failed on original bytecode: {result.stderr}"
        )

        # Compare emulator output to expected config
        output = result.stdout.strip()
        lines = [l.strip() for l in output.split("\n") if l.strip()]
        assert len(lines) == 4, (
            f"Emulator produced {len(lines)} lines, expected 4"
        )

        full = "\n".join(lines)
        h = hashlib.sha256(full.encode()).hexdigest()
        assert h == EXPECTED_FULL_HASH, (
            "Emulator output on original bytecode does not match expected config"
        )

    def test_emulator_handles_empty_data(self):
        """Emulator must accept a single argument (bytecode only, no data file)."""
        # Create trivial bytecode: just HLT (0xFF)
        hlt_tmp = "/tmp/test_hlt.bin"
        with open(hlt_tmp, "wb") as f:
            f.write(bytes([0xFF]))

        result = subprocess.run(
            ["python3", EMULATOR_PATH, hlt_tmp],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, (
            f"Emulator failed on HLT-only bytecode: {result.stderr}"
        )
        # HLT with no output instructions should produce empty output
        assert result.stdout.strip() == "", (
            f"Expected empty output from HLT-only bytecode, got {result.stdout!r}"
        )


class TestPayload:
    """Verify the agent-authored bytecode produces the correct target output."""

    def test_payload_exists(self):
        assert os.path.isfile(PAYLOAD_PATH), f"{PAYLOAD_PATH} not found"

    def test_payload_size_constraint(self):
        """Payload must be at most 64 bytes."""
        size = os.path.getsize(PAYLOAD_PATH)
        assert size <= PAYLOAD_MAX_SIZE, (
            f"payload.bin is {size} bytes, maximum allowed is {PAYLOAD_MAX_SIZE}"
        )
        assert size > 0, "payload.bin must not be empty"

    def test_payload_output(self):
        """Running the emulator on payload.bin (no data) must output ANALYSIS_PASS."""
        assert os.path.isfile(EMULATOR_PATH), (
            f"{EMULATOR_PATH} required to verify payload"
        )

        result = subprocess.run(
            ["python3", EMULATOR_PATH, PAYLOAD_PATH],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, (
            f"Emulator failed on payload.bin: {result.stderr}"
        )

        output = result.stdout.strip()
        assert output == PAYLOAD_TARGET, (
            f"Expected '{PAYLOAD_TARGET}', got {output!r}"
        )

    def test_payload_uses_valid_opcodes(self):
        """Payload bytecode must only contain documented opcodes."""
        assert os.path.isfile(OPCODES_PATH), "opcodes.json required"
        assert os.path.isfile(PAYLOAD_PATH), "payload.bin required"

        with open(OPCODES_PATH, "r") as f:
            opcode_data = json.load(f)

        valid_opcodes = set()
        for key in opcode_data:
            norm = normalize_opcode_key(key)
            if norm is not None:
                valid_opcodes.add(norm)

        with open(PAYLOAD_PATH, "rb") as f:
            payload = f.read()

        # Walk the bytecode using the documented sizes
        opcode_sizes = {}
        for key, val in opcode_data.items():
            norm = normalize_opcode_key(key)
            if norm is not None and isinstance(val, dict) and "size" in val:
                opcode_sizes[norm] = val["size"]

        pc = 0
        while pc < len(payload):
            op = payload[pc]
            assert op in valid_opcodes, (
                f"Payload byte at offset {pc}: 0x{op:02X} is not a valid opcode"
            )
            size = opcode_sizes.get(op, 1)
            pc += size
