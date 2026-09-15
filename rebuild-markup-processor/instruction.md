A stripped binary at `/app/arkv` implements a custom binary archive format. Only minimal documentation is provided in `/app/README.txt`; it does not cover the complete feature set.

Your task: reverse-engineer the binary's complete behavior — including the proprietary binary archive format, all supported commands (both documented and undocumented), environment variable controls, and all internal algorithms — then create a fully compatible Python reimplementation at `/app/arkv.py`.

The reimplementation must:
- Support every command the binary supports (discover them all)
- Produce byte-identical archive files for the same inputs and environment
- Successfully read archives created by the reference binary and vice versa
- Replicate all error conditions and exit codes
- Match all stdout output exactly