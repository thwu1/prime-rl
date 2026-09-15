A stripped (no debug symbols) reference binary at `/app/pktool-ref` implements a packet analyzer for the MeshLink Protocol (MLP), a custom binary network protocol. A partial specification is at `/app/protocol_spec.md` and sample captures are in `/app/samples/`.

Create an executable at `/app/pktool` that is behaviorally equivalent to the reference binary across all subcommands: `decode`, `validate`, `stats`, `filter`, and `reassemble`. Your implementation must produce identical output (stdout, stderr, exit codes) for any valid or malformed MLP packet input.

The specification is deliberately incomplete. Several critical behaviors are undocumented:

- Payload scrambling on secure channels (128+) uses a keystream generator seeded from header fields. The algorithm, characteristic polynomial, seed derivation, and zero-seed edge case must be reverse-engineered from the binary — simple XOR guesses will not match.
- The tool tracks internal state across packets within a file, producing context-dependent output not inferable from individual packets alone.
- Fragment reassembly resolves conflicting metadata in ways not described by the spec.

Your tool must NOT be a copy or symlink of the reference binary.