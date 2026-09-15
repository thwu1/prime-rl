The speed enforcement server for Freedom Island's road network has been lost. The only surviving artifacts are a partial protocol specification and captured session recordings from the production server.

Available at `/app/`:

- `spec.txt` — A recovered fragment of the binary protocol specification. Covers wire format and message layouts only. The behavioral rules section (speed calculation, ticket issuance logic, deduplication policy, error conditions, heartbeat semantics, dispatcher routing) was stored in a separate document that could not be recovered.
- `traces/` — Six network session recordings captured from the production server before it failed. These demonstrate the full range of correct server behaviors including subtle edge cases not documented in the specification fragment.

Implement the server at `/app/server.py`. It must listen on TCP port 9999 and handle concurrent client connections. The session recordings are your sole reference for all behavioral rules absent from the specification — analyze them to determine the correct semantics for speed violation detection, ticket generation and deduplication, error handling, heartbeat scheduling, and dispatcher-based ticket delivery.