# Citation Reliability Evaluation Framework

## Evaluation Philosophy

This framework evaluates citation quality in legal language model outputs
through multi-dimensional analysis. It draws on established information
retrieval metrics adapted for the unique challenges of legal citation,
where U.S. Bluebook conventions govern citation formatting across federal
and state reporter systems.

## Data Architecture

The evaluation integrates data from heterogeneous sources referenced in the
configuration file. Each source uses a format selected for compatibility
with specific analysis tools. The evaluator must discover and correctly
parse all configured data sources, handling format-specific requirements.

## Citation Extraction and Normalization

Citations follow standard Bluebook volume-reporter-page notation. The
extraction must correctly identify citations across all major reporter
families:

**Federal reporters:** U.S. Reports (U.S.), Supreme Court Reporter
(S. Ct.), Lawyers' Edition (L. Ed., L. Ed. 2d), Federal Reporter
(F., F.2d, F.3d, F.4th), Federal Supplement (F. Supp., F. Supp. 2d,
F. Supp. 3d).

**Regional reporters:** Atlantic (A.2d, A.3d), Southern (So.2d, So.3d),
South Western (S.W.2d, S.W.3d), North Western (N.W.2d, N.W.3d),
North Eastern (N.E.2d, N.E.3d), South Eastern (S.E., S.E.2d),
Pacific (P.2d, P.3d).

**State-name reporters:** Jurisdictions that use the state name as the
reporter designator, such as Idaho or Hawai'i (note the okina
diacritical mark in Hawaiian usage).

**Compound state reporters:** Some states use multi-word reporter names
that incorporate series designators, such as Ohio St. 3d, Cal. Rptr. 2d,
N.Y.S.2d, or Wis. 2d. The series number is part of the reporter name,
not the volume or page.

Citations appearing in model outputs may be embedded in case names,
parenthetical year references, or pinpoint page citations. The extraction
process must identify the core volume-reporter-page triple while
filtering out non-citation numeric patterns.

Responses that contain no extractable legal citations are classified as
"non-concrete" (typically refusals or abstentions). Responses with at
least one extractable citation are "concrete."

## Parallel Citation Equivalence

In U.S. legal practice, the same judicial opinion is frequently published
in multiple reporter systems simultaneously (parallel publication). For
example, a U.S. Supreme Court opinion appears in U.S. Reports, Supreme
Court Reporter, and Lawyers' Edition — all citing the same case. The
evaluation database provides a cross-reference table mapping known
equivalent citations across reporter systems. Citation matching must
account for these equivalences: a prediction citing a case in one reporter
should receive credit when the reference citation uses a different reporter
for the same opinion.

## Retrieval Quality Assessment

Citation retrieval quality is measured by comparing extracted predictions
against reference citation sets. Matching uses case-insensitive
bidirectional substring containment, extended with parallel citation
equivalence from the cross-reference table. Each reference citation can
be consumed by at most one prediction (greedy one-to-one assignment).
Standard information retrieval metrics quantify per-record performance on
a 0-100 scale.

Category-level and overall per-model averages are arithmetic means of
per-record scores. Cross-model normalization divides each model's category
average by the best-performing model's category average; the normalized
overall score is the mean of normalized category scores.

## Jurisdiction-Weighted Assessment

Citations carry different evaluative weight based on the court's position
in the judicial hierarchy. Higher courts produce more authoritative
precedent, reflected in configurable scoring weights associated with each
jurisdiction level. The weighted overall score for a model is the weighted
average of its per-record scores, where weights derive from the
jurisdiction associated with each record.

## Misleading Answer Rate

MAR quantifies how frequently a model gives a substantive but inaccurate
response rather than acknowledging uncertainty. It examines responses
scoring at or below a configured threshold and measures the proportion
that are concrete. When no responses fall at or below the threshold for
a given model, that model's rate is null (not zero). The overall rate
pools qualifying responses across all models.

## Fabrication Analysis

Fabrication rate measures the prevalence of wholly invented citations.
A predicted citation is considered fabricated if it cannot be matched to
any reference citation in the corresponding record through either direct
matching or parallel citation equivalence. The per-model rate is the ratio
of fabricated to total extracted citations. Models producing no citations
have a rate of zero.

## Citation Error Detection

Error analysis examines structured pairs of presented and canonical
citation forms. Each citation decomposes into a (volume, reporter, page)
triple. Discrepancies between presented and canonical forms are classified
by the altered component: volume, reporter, or page. Each error type
carries a severity weight reflecting practical impact. Detection accuracy
measures correct identification of error presence; classification accuracy
and its severity-weighted variant measure correct error type determination
among error-containing pairs.
