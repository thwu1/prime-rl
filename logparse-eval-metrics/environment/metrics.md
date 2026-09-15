
# Loghub-2.0 Evaluation Metrics — Formal Specification

## Notation

- **N**: total number of log messages (after null filtering)
- **G = {G₁, G₂, …, Gₖ}**: ground truth partition — each Gᵢ is the set of message indices sharing ground truth template gᵢ
- **P = {P₁, P₂, …, Pₘ}**: parsed partition — each Pⱼ is the set of message indices sharing parsed template pⱼ
- **k = |G|**: number of unique ground truth templates
- **m = |P|**: number of unique parsed templates

## Preprocessing

Before computing any metric, filter out all messages whose ground truth EventTemplate is null or NaN. Apply this filter to both ground truth and parsed output simultaneously, preserving row alignment. All metrics below operate on the filtered dataset.

## Metric 1: Grouping Accuracy (GA)

GA evaluates whether the parser correctly groups messages that belong to the same event type.

**Definition of "accurately grouped":**
A ground truth group Gᵢ is accurately grouped if and only if both conditions hold:

1. **Homogeneity**: All messages in Gᵢ are assigned the same parsed template. Formally, |{pⱼ : j ∈ Gᵢ}| = 1. Let this unique parsed template be p*.
2. **Completeness**: The parsed group containing p* has exactly the same size as Gᵢ. Formally, |{idx : parsed[idx] = p*}| = |Gᵢ|.

Together, these ensure a bijective correspondence: Gᵢ maps entirely to one parsed group, and that parsed group contains only members of Gᵢ.

**Formula:**

    GA = (Σ |Gᵢ|, for all accurately grouped Gᵢ) / N

## Metric 2: F-Measure of Grouping Accuracy (FGA)

FGA captures the precision and recall of accurate grouping at the template level.

Let **A** = number of accurately grouped ground truth templates (from GA computation).

    PGA = A / m       (precision: fraction of parsed templates that are accurate)
    RGA = A / k       (recall: fraction of ground truth templates that are accurately recovered)
    FGA = 2 · PGA · RGA / (PGA + RGA)    (harmonic mean; 0 if both are 0)

## Metric 3: Parsing Accuracy (PA)

PA measures the fraction of individual messages whose parsed template string exactly equals the ground truth template string.

    PA = |{i : parsed_template[i] == gt_template[i]}| / N

This is a character-level exact string match — no fuzzy matching, no normalization.

## Metric 4: F-Measure of Template Accuracy (FTA)

FTA evaluates whether each unique parsed template correctly identifies exactly one ground truth template.

**Computation (group by parsed template):**

For each unique parsed template pⱼ, let **oracle_set(pⱼ)** = the set of distinct ground truth templates associated with messages assigned to pⱼ:

    oracle_set(pⱼ) = {gt_template[i] : parsed_template[i] = pⱼ}

A parsed template pⱼ is **correctly identified** if and only if:

    oracle_set(pⱼ) = {pⱼ}

That is, (a) all messages with parsed template pⱼ share exactly one ground truth template, AND (b) that ground truth template text equals pⱼ itself.

Let **C** = number of correctly identified parsed templates.

    PTA = C / m       (precision: fraction of parsed templates that are correct)
    RTA = C / k       (recall: fraction of ground truth templates that are correctly identified)
    FTA = 2 · PTA · RTA / (PTA + RTA)    (harmonic mean; 0 if both are 0)

## Key Distinctions

- **GA vs PA**: GA checks grouping structure (same cluster?), PA checks template text (exact string match?). A parser can have perfect GA but poor PA if groupings are correct but template text is wrong.
- **FGA vs FTA**: FGA is based on grouping accuracy (groups by ground truth template). FTA is based on template text accuracy (groups by parsed template and checks text equality). They use different grouping directions and different correctness criteria.
- **GA vs FGA**: GA is message-weighted (each message contributes equally). FGA is template-weighted via precision/recall (each template contributes equally regardless of frequency).
