Implement `/app/spirv_tool.py`, a Python tool that operates directly on SPIR-V shader module binaries. The tool must parse and manipulate the binary format programmatically — do not shell out to `spirv-as`, `spirv-dis`, `spirv-opt`, or `spirv-link` for any of the core logic.

An opcode reference mapping opcodes to their operand layouts (which words are IDs vs. literals vs. strings) is at `/app/spirv_reference.json`. Pre-assembled SPIR-V test binaries are in `/app/modules/`. The command-line tools `spirv-dis`, `spirv-val`, and `spirv-opt` are installed for inspection and debugging.

The tool must support four subcommands:

**`python3 /app/spirv_tool.py analyze <input.spv>`** — Parse the SPIR-V binary and print a JSON report to stdout containing: `header` (magic number, version, generator, bound, schema), `entry_points` (list with name and execution_model string), `functions` (list with name from OpName and numeric id), and `capabilities` (list of capability name strings).

**`python3 /app/spirv_tool.py strip-dead <input.spv> <output.spv>`** — Produce a valid SPIR-V module containing only functions that are actually needed at runtime. Functions that no entry point (or exported linkage target) can ever invoke must be eliminated, along with any debug or annotation instructions that exclusively reference removed entities. The output must pass `spirv-val`.

**`python3 /app/spirv_tool.py compact <input.spv> <output.spv>`** — Produce a valid SPIR-V module where the ID space has no gaps — IDs must form a contiguous range `[1, N]` and the header bound must equal `N + 1`. The output must be semantically equivalent to the input and pass `spirv-val`.

**`python3 /app/spirv_tool.py merge <a.spv> <b.spv> <output.spv>`** — Combine two independent SPIR-V modules into a single valid module that contains all entry points and functions from both inputs. The merged output must conform to the SPIR-V specification (no ID collisions, no duplicate type declarations where the spec forbids them, exactly one OpMemoryModel, no duplicate capabilities). The output must pass `spirv-val`.