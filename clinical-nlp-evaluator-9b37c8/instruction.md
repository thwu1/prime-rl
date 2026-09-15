Build a clinical NLP evaluation engine at `/app/clinical_eval/` that scores entity extraction, relation extraction, and attribute assignment system outputs against gold-standard annotations.

**Environment**

Annotation format specifications and evaluation methodology are documented in `/app/data/spec.md`. Sample annotated documents in both supported formats are under `/app/data/`. The engine must auto-detect annotation format per directory and support cross-format evaluation (e.g., brat gold vs. XML system).

**CLI**

```
python3 /app/clinical_eval/evaluate.py \
  --gold <dir> --system <dir> \
  --matching {strict,overlap,type} \
  [--threshold 0.5] \
  --output <json_path>
```

**Document-set handling**

Gold and system directories may contain non-overlapping document sets. Documents appearing only in gold contribute false negatives for all their annotations. Documents appearing only in system contribute false positives for all their annotations. Both per-document and aggregate metrics must reflect these asymmetries.

**Output JSON schema**

```json
{
  "matching_mode": "strict",
  "threshold": 0.5,
  "entity_metrics": {
    "<Type>": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": 0, "fn": 0}
  },
  "relation_metrics": {
    "<Type>": {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": 0, "fn": 0}
  },
  "attribute_metrics": {
    "<AttrType>": {"accuracy": 0.0, "correct": 0, "total": 0}
  },
  "micro": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
  "macro": {"precision": 0.0, "recall": 0.0, "f1": 0.0},
  "per_document": {
    "<doc_id>": {
      "entity_metrics": {},
      "relation_metrics": {},
      "attribute_metrics": {},
      "micro": {},
      "macro": {}
    }
  }
}
```

Per-document entries use the same sub-schema as aggregate. Zero denominators yield 0.0. An annotation type appears in a document's metrics only if that type occurs in the gold or system annotations for that document.

**Success criteria**

All tests pass. The engine correctly handles: multiple entity types, discontinuous spans, cross-format evaluation, empty annotations, configurable thresholds, document-set asymmetry, and optimal one-to-one entity assignment.
