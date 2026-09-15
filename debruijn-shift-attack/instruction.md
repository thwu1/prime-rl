The SIGMA-7 facility uses shift-register based fixed-code receivers across five security zones. Zone parameters, physical encoding tables, and the master authentication seed are stored in proprietary binary formats and encrypted files — no human-readable documentation is provided for any of them.

## Environment

- `/app/receiver.py` — Receiver service daemon (UDP port 7331, custom binary protocol). Start it before interacting. SUBMIT commands require a 16-byte authentication key derived from the master seed.
- `/app/zones.dat` — Zone configuration in packed binary format. Contains zone parameters (alphabet sizes, code lengths, flags), physical encoding lookup tables, and a passphrase field.
- `/app/seed.enc` — AES-256-CBC encrypted master seed (PBKDF2 key derivation, 100000 iterations). The decryption passphrase is embedded in `zones.dat`.

Protocol analysis tools (`tshark`, `socat`, `xxd`) and decryption utilities (`openssl`) are installed.

Zones use varying alphabet sizes, code lengths, and physical encoding layers. Two zones use standard shift-register receivers. One zone applies OOK (On-Off Keying) physical encoding where each logical symbol maps to a multi-bit pattern. One zone uses tri-state physical encoding modeled on real commercial garage door systems where each of three logical symbols maps to an 18-bit physical pattern. One zone monitors a single bitstream with five receivers of different code lengths simultaneously.

For encoded zones, the receiver expects physical bitstreams (not logical symbols) in SUBMIT payloads. Encoding tables are available only in `zones.dat`.

Crack all five zones by generating optimal symbol sequences that exploit shift-register behavior, then write:

**`/app/results.json`:**
```json
{
  "A": {"code": "<code_string>", "sequence_length": <int>},
  "B": {"code": "<code_string>", "sequence_length": <int>},
  "C": {"code": "<code_string>", "sequence_length": <int>, "physical_length": <int>},
  "D": {"code": "<code_string>", "sequence_length": <int>, "physical_length": <int>},
  "E": {
    "8": {"code": "<code_string>"},
    "9": {"code": "<code_string>"},
    "10": {"code": "<code_string>"},
    "11": {"code": "<code_string>"},
    "12": {"code": "<code_string>"},
    "sequence_length": <int>
  }
}
```

Save each zone's logical symbol sequence (space-separated integers) to `/app/sequences/<ZONE>.txt`. For encoded zones, also save the physical bitstream to `/app/sequences/<ZONE>_physical.txt`.