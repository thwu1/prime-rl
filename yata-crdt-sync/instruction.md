Build a Python module at `/app/yjs_compat.py` that decodes and encodes Yjs V1 binary update messages, achieving cross-language interoperability with the real Yjs JavaScript library.

The environment provides:

- Node.js with `yjs@13.6.20` installed at `/app/node_modules/`
- A validation oracle at `/app/yjs_oracle.js` for cross-language verification
- A wire format specification at `/app/wire_format.md`
- Pre-generated binary fixtures at `/app/fixtures/` with metadata in `manifest.json`

Your module must implement a `YDoc` class with:

- `get_text(name) -> YText`: get or create a named text sequence
- `get_state_vector() -> dict`: compute `{client_id: next_clock}` mapping
- `encode_state_as_update_v1(target_sv=None) -> bytes`: encode full state or diff as Yjs V1 binary update
- `apply_update_v1(data: bytes)`: decode and apply a Yjs V1 binary update message
- `snapshot() -> dict`: capture current state for time-travel reconstruction
- `text_at_snapshot(name, snap) -> str`: reconstruct text at a prior snapshot

`YText` must support `insert(index, text)`, `delete(index, length)`, `__str__()`, and `__len__()`.

Binary updates produced by your module must be consumable by the real Yjs library (verified via `node /app/yjs_oracle.js apply <textName> <binaryFile>`). Binary updates produced by Yjs (the fixtures) must be correctly decoded by your module. Concurrent edits from multiple clients must converge identically in both Python and JavaScript using the YATA conflict resolution algorithm.

The wire format spec describes the binary layout including variable-length integers, struct info bytes, and content type encoding. For the YATA conflict resolution algorithm, consult the Yjs source at `/app/node_modules/yjs/dist/yjs.mjs` or the high-level description in the wire format spec.