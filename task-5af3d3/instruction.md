The SDSL v3 succinct data structure library (C++17, header-only) is installed at `/opt/sdsl-lite`. Input data and a working `CMakeLists.txt` are at `/app/`.

Write `/app/analyzer.cpp` — a C++ program that constructs wavelet-tree and compressed-suffix-array indexes over the provided data, answers all queries, evaluates space usage across multiple index configurations, and writes results to `/app/results.json`.

## Integer sequence range queries

`/app/sequence.txt` contains 50,000 space-separated integers in [0, 511]. Build a `wt_int<>` wavelet tree and answer each line of `/app/range_queries.txt` (all ranges are half-open [l, r)):

- `QUANTILE l r k` — k-th smallest value (0-indexed) among positions [l, r)
- `DISTINCT l r` — number of distinct values in [l, r)
- `TOPFREQ l r` — most frequent value in [l, r); ties broken by smallest value
- `PREVVAL l r v` — largest value ≤ v appearing in [l, r), or −1 if none
- `NEXTVAL l r v` — smallest value ≥ v appearing in [l, r), or −1 if none

## Text corpus queries

`/app/corpus.txt` contains 30,000 characters (lowercase letters and spaces). Construct a `csa_wt<wt_huff<>>` and answer each line of `/app/text_queries.txt`:

- `COUNT pattern` — total occurrences of pattern in corpus (including overlapping)
- `LOCATE pattern k` — first k occurrence positions (0-indexed), sorted ascending

## Space evaluation

Construct wavelet trees over the integer sequence with three backing bitvector types and report `size_in_bytes` for each: `wt_int<bit_vector>`, `wt_int<rrr_vector<63>>`, `wt_int<rrr_vector<15>>`. Construct three CSA variants over the text corpus and report sizes: `csa_wt<wt_huff<>>`, `csa_sada<>`, `csa_bitcompressed<>`. Identify the smallest configuration in each category.

## Output format (`/app/results.json`)

```json
{
  "range_results": [/* one integer per range query, in file order */],
  "text_count_results": [/* one integer per COUNT query */],
  "text_locate_results": [/* one sorted position array per LOCATE query */],
  "space_analysis": {
    "wt_bit_vector": <bytes>,
    "wt_rrr_63": <bytes>,
    "wt_rrr_15": <bytes>,
    "csa_wt_huff": <bytes>,
    "csa_sada": <bytes>,
    "csa_bitcompressed": <bytes>,
    "smallest_wt": "<name of smallest WT>",
    "smallest_csa": "<name of smallest CSA>"
  }
}
```

Build: `mkdir -p /app/build && cd /app/build && cmake .. && make`