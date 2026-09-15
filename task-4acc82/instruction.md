A data processing pipeline at `/app/` has two broken components that must be fixed.

## Aho-Corasick Multi-Pattern Matcher

`/app/aho_corasick.py` implements the Aho-Corasick algorithm for simultaneous multi-pattern string matching over byte sequences. The automaton construction has a correctness bug that causes it to silently miss matches for patterns that happen to be suffixes of other patterns' trie paths — the failure function is computed correctly, but the information it carries is not fully propagated during construction. Three search modes are also unimplemented: `find_leftmost_first` (non-overlapping, first-pattern-wins semantics like Perl regex alternation), `find_leftmost_longest` (non-overlapping, longest-match-wins semantics like POSIX), and `find_streaming` (stateful search across chunked input maintaining automaton state between chunks).

Fix the implementation in-place at `/app/aho_corasick.py`. The CLI at `/app/cli.py` exercises the module and must not be modified.

## Log Extraction Pipeline

`/app/pipeline.sh` uses ripgrep to extract structured error events from log files in `/app/logs/`, joins them with `/app/reference.csv` via `xsv`, and aggregates the results using `/app/aggregate.py`. The pipeline currently misses events from several log sources due to multiple blind spots in how it invokes ripgrep and processes the extracted data. Five log files exist in `/app/logs/` with different encoding, visibility, format, and case characteristics. Some produce no output at all; others produce output that is silently dropped by downstream join semantics.

The correct output contains exactly 6 unique error codes (E001–E006) totaling 16 events. Write the corrected output to `/app/output/results.csv`.

`/app/aggregate.py` is correct and must not be modified. Three reference extraction strategies in `/app/strategies/` and a runner at `/app/run_strategy.sh` are available for diagnostic comparison.