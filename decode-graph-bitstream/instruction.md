The file `/app/data/graph.bin` contains a directed graph encoded in WGEF
format — a WebGraph-inspired compression scheme that layers an
Elias-Fano monotone sequence index over reference-compressed adjacency
data using Boldi-Vigna zeta codes.

High-level structural notes are in `/app/data/NOTES.md`, but the
encoding algorithms (Elias-Fano representation, gamma codes, zeta_k
codes, minimal binary codes, copy-list block mechanism) are NOT
specified there. The C source code at `/app/tools/` is the authoritative
reference: `bitstream.c` implements every coding primitive, and the
diagnostic tools (`header_info`, `ef_dump`, `bitprobe`) demonstrate how
the header and index sections are parsed. Build the toolkit, study the
source, use the tools for validation, and implement a complete decoder.

The format has interacting layers that must be understood holistically:
the Elias-Fano index provides per-node bit offsets into a node data
section where each node's adjacency list is either encoded directly as
zeta_k-coded gaps, or reconstructed by copying and patching a nearby
node's previously-decoded successor list via an alternating copy/skip
block mechanism — a scheme that requires understanding both the
reference compression algorithm and the interaction between sequential
decoding order and the offset index.

Write two output files:
- `/app/output/adjacency.json` — the full decoded graph as a JSON array
  of arrays, where element `i` is the sorted successor list of node `i`
- `/app/output/answers.txt` — one answer per line for the queries in
  `/app/data/queries.txt`, in the same order