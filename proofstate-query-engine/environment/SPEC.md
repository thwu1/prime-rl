# Proof-State Query Engine — Specification


## 1. Proof State JSON Format

A proof state document is a JSON array of **fragments**. Each fragment is an
array of **items**. An item is either a **sentence** or a **text** node.

### Text node

```json
{"_type": "text", "string": "..."}
```

### Sentence

```json
{
  "_type": "sentence",
  "sentence": "exact I.",
  "responses": ["..."],
  "goals": [<Goal>, ...]
}
```

- `sentence`: the source text of the proof sentence
- `responses`: array of message strings (prover output, e.g. from `Print` or `Check`)
- `goals`: array of Goal objects representing the proof state after this sentence

### Goal

```json
{
  "_type": "goal",
  "name": "1",
  "conclusion": "forall n : nat, ...",
  "hypotheses": [<Hypothesis>, ...]
}
```

- `name`: a string identifier (may be numeric like `"1"`) or `null` for unnamed goals
- `conclusion`: the goal's conclusion string
- `hypotheses`: array of Hypothesis objects

### Hypothesis

```json
{
  "_type": "hypothesis",
  "name": "IHn'",
  "body": null,
  "type": "forall m : nat, n' + m = m + n'"
}
```

- `name`: the hypothesis name
- `body`: the hypothesis body (a string if it has a `let`-binding, otherwise `null`)
- `type`: the hypothesis type

## 2. Marker-Placement Path Syntax

Paths are dot-separated sequences of **segments**. Each segment selects or
filters elements from the current context.

### Grammar

```
path     ::= segment+
segment  ::= '.' selector

selector ::=
  | 's(' pattern ')'          -- sentence: literal substring match on sentence text
  | 's{' pattern '}'          -- sentence: fnmatch on full sentence text
  | 'g#' value                -- goal: by 1-based position (if value is integer) or name (fnmatch)
  | 'g(' pattern ')'          -- goal: literal substring match on conclusion
  | 'g{' pattern '}'          -- goal: fnmatch on full conclusion
  | 'h#' value                -- hypothesis: fnmatch on hypothesis name
  | 'h(' pattern ')'          -- hypothesis: literal substring in type or body
  | 'h{' pattern '}'          -- hypothesis: fnmatch on full type or body
  | 'msg'                     -- all messages (responses) of current sentence(s)
  | 'msg(' pattern ')'        -- messages: literal substring match
  | 'msg{' pattern '}'        -- messages: fnmatch match
  | 'in'                      -- sentence input text (leaf)
  | 'ccl'                     -- goal conclusion text (leaf)
  | 'name'                    -- goal or hypothesis name (leaf)
  | 'type'                    -- hypothesis type (leaf)
  | 'body'                    -- hypothesis body (leaf)
```

### Matching rules

- **Literal `(pattern)`**: matches if `pattern` is a substring of the target text.
- **Fnmatch `{pattern}`**: matches if the FULL target text matches the fnmatch pattern.
  Fnmatch special characters: `*` matches any sequence, `?` matches any single
  character, `[seq]` matches any character in seq.
- **Name `#value`**: For goals, if `value` is a valid positive integer, match by
  1-based position in the goals list. Otherwise, match goals whose `name` field
  matches `value` using fnmatch (goals with `null` name are skipped). For hypotheses,
  match by name using fnmatch.
- **Hypothesis content matching** `h(pattern)` / `h{pattern}`: matches against the
  hypothesis `type` field OR `body` field. Null bodies are treated as empty strings.

### Evaluation contexts and defaults

Evaluation proceeds left-to-right through the path segments. Each segment
transforms the current context:

| Current context | Segment type | New context |
|----------------|--------------|-------------|
| document       | `.s(...)`    | sentences   |
| sentences      | `.g...`      | goals       |
| sentences      | `.h...`      | goals (implicit `.g#1`) → hypotheses |
| sentences      | `.msg...`    | messages    |
| sentences      | `.ccl`       | strings (implicit `.g#1` → conclusion) |
| sentences      | `.in`        | strings     |
| goals          | `.h...`      | hypotheses  |
| goals          | `.g...`      | goals (further filter) |
| goals          | `.ccl`       | strings     |
| goals          | `.name`      | strings     |
| hypotheses     | `.name`      | strings     |
| hypotheses     | `.type`      | strings     |
| hypotheses     | `.body`      | strings     |

**Implicit `.g#1` default**: When `.h...`, `.ccl`, or `.name` (for goals) is used
at sentence context without an explicit `.g...` preceding it, the first goal of
each sentence is used implicitly (equivalent to prepending `.g#1`).

### Examples

- `.s(induction)` — all sentences containing "induction"
- `.s{Theorem*}` — sentences matching fnmatch pattern "Theorem*"
- `.s(induction).g#2` — second goal of induction sentences
- `.s(induction).g#2.h#IHn'` — hypothesis named "IHn'" in that goal
- `.s(induction).g#2.h#IHn'.type` — just the type string
- `.s(Base case).ccl` — conclusion of the first goal (implicit) of "Base case" sentences
- `.s(Print).msg` — all messages from "Print" sentences
- `.s(Check).msg(forall)` — messages containing "forall" from "Check" sentences
- `.s(simpl).g(m + 0)` — goals whose conclusion contains "m + 0" from simpl sentences

## 3. Structural Minification

### Minified format

```json
{
  "_refs": {
    "0": <subtree>,
    "1": <subtree>,
    ...
  },
  "data": [<fragments with $ref replacements>]
}
```

### Requirements

Minification eliminates structural redundancy in the document by factoring out
subtrees that appear multiple times.

- **Scope**: deduplication applies at the **hypothesis** and **goal** levels only.
  Text nodes, sentence objects as a whole, and fragments are never deduplicated.
- **Threshold**: a subtree is deduplicated when it occurs >= 2 times by structural
  equality (recursive JSON equality, key order irrelevant).
- **Replacement**: every occurrence of a deduplicated subtree — including the first —
  is replaced with `{"$ref": "<id>"}`. The original subtree is stored in `_refs`.
- **Layered refs**: a `_refs` entry may itself contain `$ref` placeholders. For
  example, a deduplicated goal's `hypotheses` array may contain hypothesis refs.
- **Maximality**: if a subtree at hypothesis or goal level appears >= 2 times in
  the fully-expanded document, it must be deduplicated. No redundant copies may
  remain after minification.
- **Determinism**: the `_refs` table must be reproducible. Reference IDs are
  sequential integers starting from `"0"`, assigned in the order subtrees are
  first encountered during a deterministic traversal of the document (fragments
  left-to-right, items top-to-bottom within each fragment, goals left-to-right
  within each sentence, hypotheses left-to-right within each goal). Finer-grained
  subtrees (hypotheses) are assigned IDs before coarser ones (goals).

### Expansion

Recursively replace every `{"$ref": "<id>"}` object (where `$ref` is the only
key) with the corresponding entry from `_refs`. The expansion of refs that
themselves contain `$ref` entries must be resolved recursively.

After expansion, the result must be identical to the original document.

## 4. CLI Interface

```
python3 /app/proofquery.py query '<path>' <json_file>
```
Print matched elements as a JSON array to stdout. The tool must transparently
handle both regular and minified documents (auto-detect by checking for `_refs`
and `data` keys; expand before querying if minified).

```
python3 /app/proofquery.py minify <json_file> -o <output_file>
```
Write the minified document to `output_file`.

```
python3 /app/proofquery.py expand <minified_json> -o <output_file>
```
Write the fully expanded document to `output_file`.

```
python3 /app/proofquery.py jqgen '<path>' <json_file>
```
Print a `jq` filter expression to stdout. When this expression is executed as
`jq '<filter>' <json_file>`, the result must be a JSON array identical to the
output of `query` for the same path and file. Only raw (non-minified) documents
need to be supported. The filter must be compatible with `jq` 1.7+.

```
python3 /app/proofquery.py dag <json_file>
```
Analyze the proof structure and print a proof obligation DAG as JSON to stdout.
The tool must transparently handle minified documents (auto-detect and expand).

All JSON output uses 2-space indentation.

## 5. Proof Obligation DAG

The `dag` command analyzes proof-state documents and reconstructs the proof
obligation tree for each proof, including tactic effect classification.

### Proof identification

A **proof** is a fragment that contains a `Qed.` or `Defined.` sentence. In
such a fragment, the first sentence is the declaration and the last is the
terminal. All sentences between (inclusive) form the proof.

Sentences in fragments without `Qed.`/`Defined.` are **commands**.

The **proof name** is extracted from the declaration sentence: take the second
whitespace-delimited token.

### Goal lifecycle

Each proof obligation (goal) has a lifecycle:

1. **Created** by a declaration (root goal) or a branching tactic (sub-goals)
2. **Transformed** by tactics that modify its conclusion or hypotheses
3. **Resolved** by either:
   - **Branching**: replaced by multiple sub-goals (case analysis, induction)
   - **Discharge**: the goal is proven (goals list becomes empty)

### Tactic effect classification

Classify each proof sentence based on the observable change between consecutive
proof states:

| Effect | Observable change |
|--------|-------------------|
| `declare` | First sentence of proof; creates the root goal |
| `noop` | Goal state structurally identical to previous step |
| `intro` | Focused goal gains one or more new hypotheses |
| `branch` | Multiple new goals appear (focused goal is split) |
| `transform` | Conclusion or hypothesis types change; hypothesis count unchanged |
| `discharge` | Goals become empty (focused goal is proven) |
| `close` | Terminal `Qed.` or `Defined.` sentence |

Command sentences (outside proofs) receive effect `info`.

### Focusing semantics

Coq proofs follow stack-based goal focusing: at any point, there is an ordered
set of **pending goals**, and the **first** pending goal is the **focused** goal.
All tactics operate on the focused goal:

- **Branch**: the focused goal is removed and replaced (at the front of the
  pending set) by N sub-goals, in the order they appear in the tactic's output
- **Discharge**: the focused goal is removed; the next pending goal (if any)
  becomes focused
- **Transform/Intro**: the focused goal is modified in place

Correct goal-to-tactic attribution and parent-child assignment in the output
DAG depends on accurately tracking the pending goal set through the proof.

### Output format

```json
{
  "proofs": [
    {
      "name": "<proof name>",
      "goals": [
        {
          "id": "<goal ID>",
          "conclusion": "<conclusion at creation time>",
          "parent": "<parent goal ID>" | null,
          "children": ["<child goal ID>", ...],
          "spawned_by": <step index that created this goal>,
          "resolved_by": <step index that branched or discharged this goal>,
          "resolution": "branch" | "discharge"
        }
      ],
      "steps": [
        {
          "index": <0-based index among proof sentences>,
          "sentence": "<sentence text>",
          "effect": "<effect>"
        }
      ]
    }
  ],
  "commands": [
    {"sentence": "<sentence text>", "effect": "info"}
  ]
}
```

### Goal ID assignment

Goal IDs are `"g0"`, `"g1"`, `"g2"`, ... assigned sequentially as goals are
created during proof analysis. Each proof numbers from `"g0"`. When a branching
tactic creates multiple sub-goals, they are numbered left-to-right in the order
they appear in the tactic's goal list.

### Invariants

The output must satisfy:

1. `parent` / `children` are consistent (parent lists child, child references parent)
2. Every leaf goal (empty `children`) has `resolution: "discharge"`
3. Every non-leaf goal has `resolution: "branch"`
4. `resolved_by > spawned_by` for every goal
5. Root goal has `parent: null`; all others reference a valid parent
6. The `goals` array is ordered by ID (g0, g1, g2, ...)
