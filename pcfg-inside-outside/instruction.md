Create `/app/pcfg_pipeline.sh` — a multi-tool pipeline that learns PCFG rule probabilities from an unlabeled corpus via inside-outside EM, tracks parameter evolution in a SQLite database, finds maximum-probability (Viterbi) parse trees, and renders them as SVG with graphviz.

The pipeline reads a CNF PCFG (`/app/grammar.gr`, tab-separated: `probability\tLHS\tRHS`) and a corpus (`/app/corpus.txt`, one sentence per line). Binary rules have two space-separated nonterminals on the RHS; lexical rules have a single terminal. `#` lines are comments. Start symbol = LHS of first non-comment rule. Nonterminals are symbols appearing as LHS of any rule.

```
/app/pcfg_pipeline.sh --grammar /app/grammar.gr --corpus /app/corpus.txt --iterations N
```

N is the number of EM iterations (must support 0 = initial grammar only, no re-estimation).

## Required outputs

**stdout** — JSON with keys: `initial_ll` (total corpus log-likelihood under initial grammar, natural log base e), `iteration_lls` (list of length N, total corpus LL after each EM iteration), `final_rules` (list of `[prob, "LHS", ["RHS"...]]` preserving grammar-file order), `sentence_lls` (per-sentence LL under final grammar, in corpus order).

**`/app/grammar.db`** — SQLite database with exact schema:
- `rules(rule_id INTEGER PRIMARY KEY, lhs TEXT, rhs TEXT, initial_prob REAL, final_prob REAL)` — rhs is space-separated, rule_id 0-indexed in grammar-file order
- `iterations(iteration INTEGER PRIMARY KEY, corpus_ll REAL)` — 1-indexed
- `rule_history(rule_id INTEGER, iteration INTEGER, probability REAL, PRIMARY KEY(rule_id, iteration))` — rule probability after each EM iteration
- `sentence_parses(sentence_id INTEGER PRIMARY KEY, sentence TEXT, log_likelihood REAL, viterbi_tree TEXT)` — 0-indexed; `viterbi_tree` is the max-probability parse under the final grammar in parenthesized notation, e.g. `(S (NP (Det the) (N dog)) (VP (V saw) (NP (Det the) (N cat))))`

**`/app/trees/sentence_N.svg`** — One SVG per corpus sentence (N is 0-indexed), depicting the Viterbi parse tree under the final grammar, rendered from a DOT-format intermediate via `dot -Tsvg`.