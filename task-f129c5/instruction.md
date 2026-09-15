Implement a lossless floating-point compression library based on the ALP (Adaptive Lossless floating-Point) algorithm. Read the full specification at `/app/spec.md`.

Your implementation must be a single Python module at `/app/alp.py` exposing two functions:

- `alp_compress(values: list[float | None]) -> bytes` — compress a list of f64 values (with optional `None` for nulls) into the ALP binary format described in the spec
- `alp_decompress(data: bytes) -> list[float | None]` — decompress ALP binary data back to the original values

The implementation must discover optimal exponent pairs via sampling, handle all IEEE 754 special values (NaN, ±Inf, -0.0) via exception patching, support nullable values, apply Frame-of-Reference and bit-packing to encoded integers, serialize/deserialize using the specified 32-byte header binary format, and preserve every value through a compress-then-decompress roundtrip with bitwise fidelity.