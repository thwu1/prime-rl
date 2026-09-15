Build a decoder that recovers original payloads from IEEE 802.11a/g OFDM PHY layer encoded frames.

`/app/encoder.py` implements the complete transmit coding chain. `/app/spec.md` provides the PHY parameter reference. Example encoded frames for all 8 MCS modes are in `/app/frames/` (one byte per bit, values 0x00/0x01) with metadata in `/app/frames/manifest.json`.

Produce the following files:

- `/app/viterbi.c` — C source for the shared library
- `/app/Makefile` — builds `viterbi.so` from `viterbi.c`
- `/app/viterbi.so` — compiled shared library (produced by running `make` in `/app`)
- `/app/decoder.py` — Python module that uses `viterbi.so` via `ctypes` and exports:

```python
def decode_frame(frame_bits: list[int], scrambler_seed: int) -> tuple[dict, bytes]:
```

`decode_frame` accepts the full coded bit sequence of a frame (first 48 bits are the SIGNAL field, remainder is DATA) and a scrambler seed (1-127). It returns `(signal_info, payload)` where `signal_info` is a dict with keys `"mcs"` (int, 0-7) and `"length"` (int, PSDU byte count), and `payload` is the recovered PSDU as `bytes`.

All 8 MCS modes must be supported. The decoder must correctly recover arbitrary payloads and scrambler seeds.