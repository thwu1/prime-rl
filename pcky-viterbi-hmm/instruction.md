Probabilistic context-free grammar files and a Hidden Markov Model specification are provided in `/app/data/`. Build a Python toolkit at `/app/` that can determine whether sentences are grammatical, find their most probable structural analysis with associated probability, compute the total probability mass across all valid analyses, evaluate predicted parse trees against gold standards, generate Graphviz visualizations, and decode optimal hidden state sequences from observations.

## Data

- `/app/data/grammar1.cfg`, `/app/data/grammar2.cfg` — PCFGs with `Grammar` and `Lexicon` sections. Each rule: `probability LHS->RHS_symbols`. Note that some grammar rules have three or more symbols on the right-hand side.
- `/app/data/hmm_model.txt` — HMM with sections: `Alphabet`, `States`, `StartProbability`, `TransitionProbability`, `EmissionProbability`.

## Required Interfaces

**`/app/pcky.py`** must expose:

- `Grammar.from_file(path)` → `Grammar` ready for parsing
- `parse_sentence(grammar, sentence_str)` → `dict` with:
  - `accepted` (bool): whether start symbol `S` spans the full input
  - `best_parse` (str | None): most probable derivation as bracket-notation string (e.g. `[S [NP [Det the] [Nominal [Noun flight]]] [VP ...]]`), using only nonterminal symbols defined in the original grammar file
  - `best_prob` (float): probability of that derivation
  - `total_prob` (float): probability summed over **every** valid derivation of the sentence
- `labeled_precision_recall(pred_sexpr, gold_sexpr)` → `(precision, recall)` computed from labeled `(label, start, end)` constituent spans, excluding preterminal nodes
- `parse_sexpr(s)` / `tree_to_sexpr(tree)` — bracket string ↔ nested-tuple conversions
- `tree_to_dot(sexpr_str)` → Graphviz DOT-format string representing the parse tree, with nonterminals as box nodes, terminals as ellipse nodes, and directed parent→child edges

**`/app/hmm.py`** must expose:

- `HMM.from_file(path)` → `HMM` object (must have `.states` attribute listing state names)
- `decode(hmm, observations)` → `(state_list, probability)` — optimal hidden-state path in probability space
- `decode_log(hmm, observations)` → `(state_list, log_probability)` — same computation in natural-log space

**`/app/render_trees.sh`** — Executable shell script taking two arguments: a grammar file path and a quoted sentence. It must parse the sentence, write the DOT representation to `/app/output/tree.dot`, and render it to SVG at `/app/output/tree.svg` using the Graphviz `dot` command.