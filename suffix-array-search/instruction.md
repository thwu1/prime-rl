Build a suffix array-accelerated code search engine at `/app/sasearch.py` that indexes a directory of source files and supports fast literal and regex search using suffix arrays for candidate narrowing.

A source code corpus is provided at `/app/corpus/` containing files of various types and sizes (Python, C, config, and a large generated dataset).

## Tool interface

**Index command:**
```
python3 /app/sasearch.py index <corpus_dir> <index_file>
```
Builds a persistent suffix array index over all files in the corpus directory.

**Search command:**
```
python3 /app/sasearch.py search <index_file> <pattern> [--regex] [--ignore-case] [--explain]
```

## Search modes

- **Literal** (default): Binary search on the suffix array for O(m log n) pattern lookup, where m is pattern length and n is corpus size.
- **Regex** (`--regex`): Factor the regex pattern to extract the longest mandatory literal substring, use the suffix array to narrow candidate positions, then apply the full regex only to candidate lines.
- **Case-insensitive** (`--ignore-case`): Works with both literal and regex modes. Requires maintaining a case-folded index.

## Output format

One match per line to stdout, sorted lexicographically by filename then by line number:
```
<filename>:<line_number>:<line_content>
```
Filenames are basenames relative to the corpus directory. Line numbers are 1-indexed. Each matching line appears at most once regardless of how many times the pattern occurs within it.

## Explain mode

When `--explain` is used with `--regex`, print the following diagnostic lines to stderr:
```
LITERAL_FACTOR: <the_extracted_literal_substring>
CANDIDATES: <number_of_suffix_array_candidate_positions>
MATCHES: <number_of_final_matching_lines>
```

## Index requirements

The persisted index file must contain the suffix array data structure and all file/line metadata needed for search. Its size must exceed the raw corpus size (reflecting suffix array storage overhead). Rebuilding the index from the same corpus must produce identical search results.