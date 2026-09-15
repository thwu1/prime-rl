# Clinical NLP Annotation Format Specification

## Brat Standoff Format

Each document consists of two files:
- `<docid>.txt` — raw clinical text (UTF-8, no BOM)
- `<docid>.ann` — standoff annotations (tab-separated fields)

### Entity lines (prefix `T`)

```
T<id>\t<Type> <start> <end>\t<text>
```

- `start`: 0-based character offset (inclusive)
- `end`: character offset (exclusive), matching Python slice semantics
- `text`: the text span from the source document

Discontinuous entities (spanning non-contiguous text regions) use semicolons:

```
T<id>\t<Type> <start1> <end1>;<start2> <end2>\t<combined text>
```

### Relation lines (prefix `R`)

```
R<id>\t<RelationType> Arg1:<EntityId> Arg2:<EntityId>
```

### Attribute lines (prefix `A`)

```
A<id>\t<AttributeType> <EntityId> <value>
```

Common attribute: `Assertion` with values `present`, `absent`, `hypothetical`, `conditional`, `associated_with_someone_else`.

### Example

```
T1	Drug 0 7	Aspirin
T2	Dosage 8 12	81mg
T3	ADE 29 35	nausea
R1	Dosage-Drug Arg1:T2 Arg2:T1
R2	ADE-Drug Arg1:T3 Arg2:T1
A1	Assertion T1 present
A2	Assertion T3 present
```

## Inline XML Format

```xml
<?xml version="1.0" encoding="UTF-8"?>
<ClinicalDocument>
<TEXT><![CDATA[raw clinical text]]></TEXT>
<TAGS>
<Entity id="T1" type="Drug" start="0" end="7" text="Aspirin"/>
<Relation id="R1" type="Dosage-Drug" arg1="T2" arg2="T1"/>
<Attribute id="A1" entity_id="T1" type="Assertion" value="present"/>
</TAGS>
</ClinicalDocument>
```

- `start`/`end` use the same 0-based inclusive/exclusive convention as brat
- `<Entity>` elements represent entities (no discontinuous spans in XML format)
- `<Relation>` elements link two entities by ID
- `<Attribute>` elements attach typed values to entities

## Format Auto-Detection

- Directory contains `.ann` files → brat standoff format
- Directory contains `.xml` files → inline XML format
- Gold and system directories may use **different** formats

## Evaluation Methodology

### Entity Matching

For each entity type separately, find the optimal one-to-one assignment between gold and system entities that maximizes total match quality. Each gold entity can match at most one system entity and vice versa. Three matching modes control edge eligibility:

- **strict**: all spans must match exactly (identical start/end offset lists)
- **overlap**: Jaccard index of character position sets >= configurable threshold (default 0.5), and types must match
- **type**: any character overlap >= 1 position, and types must match

Jaccard index = |intersection of character position sets| / |union of character position sets|

For discontinuous entities, the character position set is the union of `range(start, end)` across all spans.

### Relation Matching

A system relation matches a gold relation when:
1. Both argument entities (Arg1 and Arg2) have been matched in the entity matching step
2. The relation type string is identical

### Attribute Evaluation

For each matched entity pair, compare attribute values of the same attribute type. Report accuracy = correct / total evaluated, per attribute type.

### Document-Set Handling

Gold and system directories may contain different sets of documents. Evaluation covers the union of all document IDs:
- Documents present in both directories are evaluated per the matching rules above
- Documents present only in gold: all gold entities are false negatives, all gold relations are false negatives
- Documents present only in system: all system entities are false positives, all system relations are false positives

Per-document metrics are reported for every document in the union of both directories.

### Metrics

- Per entity type: precision, recall, F1, TP, FP, FN
- Per relation type: precision, recall, F1, TP, FP, FN
- Per attribute type: accuracy, correct count, total count
- Micro-averaged (entities): aggregate TP/FP/FN across all entity types
- Macro-averaged (entities): mean of per-type precision/recall/F1
- Zero denominator yields 0.0 (not NaN or error)
