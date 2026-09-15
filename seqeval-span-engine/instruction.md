Implement `/app/span_eval.py`, a sequence labeling evaluation engine that extracts entity spans and computes precision/recall/F1 metrics across six NER tagging schemes.

The program reads a JSON file (path as first CLI argument) and writes JSON to stdout.

**Input:**
```json
{
  "y_true": [["B-PER", "I-PER", "O"], ...],
  "y_pred": [["B-PER", "O", "O"], ...],
  "scheme": "IOB2",
  "mode": "strict",
  "suffix": false,
  "delimiter": "-"
}
```

`scheme`: `IOB1` | `IOB2` | `IOE1` | `IOE2` | `IOBES` | `BILOU` | `auto`. `mode`: `strict` | `default`. `suffix`: when true, tags use suffix format (`PER-B` instead of `B-PER`). Inner sequences in `y_true` and `y_pred` must have matching lengths.

**Output:**
```json
{
  "entities_true": {"PER": [[0, 0, 2]]},
  "entities_pred": {"PER": [[0, 0, 1]]},
  "per_type": {"PER": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 1}},
  "micro_avg": {"precision": ..., "recall": ..., "f1": ..., "support": ...},
  "macro_avg": {"precision": ..., "recall": ..., "f1": ..., "support": ...},
  "weighted_avg": {"precision": ..., "recall": ..., "f1": ..., "support": ...},
  "detected_scheme": "IOB2"
}
```

Entity spans: `[sent_id, start, end)` half-open, sorted by `(sent_id, start, end)`. Tags without an entity type (bare `B`) use type `_`. `detected_scheme` included only when input `scheme` is `auto`.

**Strict mode** evaluates entities using each scheme's canonical state-transition rules governing valid entity starts, continuations, and ends. Each of the six schemes defines a distinct set of allowed tag prefixes and distinct transition semantics governing how tag sequences map to entity boundaries. Invalid prefixes for the declared scheme must raise `ValueError`.

**Default mode** uses conlleval-compatible boundary detection. The reference conlleval.pl script is at `/app/conlleval.pl` — study its `startOfChunk` and `endOfChunk` subroutines to understand the exact semantics.

**Auto-detect**: Determine the scheme from the set of tag prefixes observed in y_true. Must distinguish IOB2, IOE2, IOBES, and BILOU by their characteristic prefix subsets. Raise `ValueError` for unrecognizable prefix combinations.

**Metrics**: Entity match requires identical `(sent_id, type, start, end)`. Types = union from y_true and y_pred. `precision=TP/(TP+FP)`, `recall=TP/(TP+FN)`, `F1=2PR/(P+R)`. Zero denominators -> 0.0. `micro_avg`: globally aggregated. `macro_avg`: unweighted per-type mean. `weighted_avg`: support-weighted mean. Support in all averages = total y_true entity count.

**Environment**: `/app/baseline.py` contains a partial implementation with known bugs and missing features. `/app/data/sample.conll` provides evaluation data in CoNLL column format (`token gold_tag predicted_tag`, blank-line sentence separators) with `/app/data/sample.eval` showing the expected conlleval.pl output for cross-validation of default-mode semantics.
