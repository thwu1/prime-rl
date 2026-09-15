Build a Rust CLI tool at `/app/` that replays collaborative editing traces and produces the final merged document.

Editing traces are at `/app/traces/*.json`. Each trace is a JSON object with:

- `numAgents` (integer): count of editing agents, identified by 0-based indices
- `txns` (array): transactions in topological order (all parents precede their children), each with:
  - `parents` (array of integers): indices of parent transactions; empty means the document starts as `""`
  - `agent` (integer): the authoring agent's index
  - `patches` (array): sequential edits as `[position, delete_count, insert_string]` tuples; `insert_string` may be absent for pure deletions; positions are unicode codepoint offsets relative to the document state after preceding patches in the same transaction have been applied

Transactions form a directed acyclic graph. A transaction with one parent continues a linear history. A transaction with multiple parents is a merge point combining divergent branches. The final transaction in the array transitively succeeds all others.

**Merge behavior:**

Each transaction observes the state produced by the cumulative effect of all its ancestors. When branches diverge and later merge:

- Every insertion made on any branch appears in the merged result
- Every deletion made on any branch is applied; redundant deletions of the same character across branches take effect only once
- Characters retain their relative ordering from whichever branch introduced them
- Concurrent insertions targeting the same document position are ordered by agent index, with the lower index placed leftward

The output must be deterministic regardless of which order the parents of a merge transaction are listed.

**Interface:**

Running `cargo run --release -- <path_to_trace.json>` prints the final document to stdout with no trailing newline added by the program. The project must compile with `cargo build --release` on the system Rust toolchain (1.75+). External crates are permitted.

The program must correctly handle: linear edit chains, two-way fork-merge diamonds, three-or-more-way merges, cascaded diamonds, concurrent same-position inserts with tie-breaking, overlapping cross-branch deletions, and interleaved delete-plus-insert conflicts.
