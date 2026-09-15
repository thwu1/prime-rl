# CRD Engine Specification

## CAP Class Banding

Map kUA/L concentration to CAP class 0–6 using **strict less-than** at each upper boundary:

| Class | Range (kUA/L) | Label |
|-------|---------------|-------|
| 0     | < 0.10        | Absent/undetectable |
| 0 (equivocal) | 0.10 – < 0.35 | Very low / equivocal (report as numeric 0) |
| 1     | 0.35 – < 0.70 | Low |
| 2     | 0.70 – < 3.50 | Moderate |
| 3     | 3.50 – < 17.50 | High |
| 4     | 17.50 – < 50.00 | Very high |
| 5     | 50.00 – < 100.00 | Ultra high |
| 6     | >= 100.00 | Extremely high |

Note: all upper boundaries use strict less-than (`<`), not less-than-or-equal.

## sIgE/tIgE Ratio

```
ratio = sIgE / totalIgE
```

- If `totalIgE` is 0 or negative, ratio = 0.
- Cap the ratio at 1.0 (it cannot exceed 1.0 in the report).

## Cross-Reactivity Resolution

### Grouping

1. Filter to positive results only (CAP class >= 1).
2. Group positive results by `molecularFamily`.
3. Allergens with no `molecularFamily` are handled separately (see below).

### Scoring within a Family Group

For each allergen in a group, compute:

```
score = sIgE * typeWeight * specificityWeight
```

**Type weights:**

| AllergenType | Weight |
|-------------|--------|
| MAJOR       | 2.0    |
| MINOR       | 1.0    |

**Specificity weights** (more specific = higher weight):

| CrossReactivityLevel | Weight |
|---------------------|--------|
| NONE                | 3.0    |
| LOW                 | 2.5    |
| MODERATE            | 2.0    |
| PROBABLE            | 1.5    |
| HIGH                | 1.0    |

### Classification Rules

- **Family group with > 1 member:** The allergen with the highest score is `PRIMARY`. All others are `CROSS_REACTIVE`.
- **Family group with exactly 1 member:** That allergen is `PRIMARY`.
- **No molecular family:** `PRIMARY` if the allergen is MAJOR type OR CAP class >= 3. Otherwise `UNDETERMINED`.
- **CAP class 0:** Always `UNDETERMINED` (regardless of other properties).

## Risk Level

Evaluate in order (first match wins):

1. `NEGLIGIBLE` — CAP class 0
2. `VERY_HIGH` — allergen has `molecularFamily === "STORAGE_PROTEINS"` AND CAP class >= 3
3. `HIGH` — allergen type is `MAJOR` AND symptoms include `"SEVERE"` AND CAP class >= 2
4. `MODERATE` — allergen type is `MAJOR` AND CAP class >= 2
5. `LOW` — all other positive results

## AIT Eligibility

An allergen is eligible for Allergen Immunotherapy (AIT) when ALL of the following hold:

- Classification is `PRIMARY`
- Type is `MAJOR`
- CAP class >= 2
- `crossReactivityLevel` is NOT `"HIGH"` (panallergens with HIGH cross-reactivity are poor AIT targets)

## Syndrome Detection

All syndromes use CAP class >= 1 as the positivity threshold. Each detected syndrome must include:
- `name`: the syndrome name (exact strings below)
- `involved_allergens`: array of allergen IDs that triggered the detection
- `evidence`: brief textual description of the finding

### 1. Pollen-Food Allergy Syndrome

**Name:** `"Pollen-Food Allergy Syndrome"`

**Condition:** At least one positive PR-10 allergen from a pollen category (category ends with `"_POLLENS"`) AND at least one positive PR-10 allergen from a food category (category starts with `"FOOD_"`).

**Involved allergens:** All positive PR-10 allergens (both pollen and food) participating in the match.

### 2. LTP Syndrome

**Name:** `"LTP Syndrome"`

**Condition:** At least 2 positive LTP allergens from different `source` values.

**Involved allergens:** All positive LTP allergens.

### 3. Pork-Cat Syndrome

**Name:** `"Pork-Cat Syndrome"`

**Condition:** A positive SERUM_ALBUMINS allergen with source `"Cat"` AND a positive SERUM_ALBUMINS allergen whose source contains `"Cow"` (case-sensitive substring match).

**Involved allergens:** The matching cat and bovine serum albumin allergens.

### 4. Bird-Egg Syndrome

**Name:** `"Bird-Egg Syndrome"`

**Condition:** Allergen with id `"f75"` (Gal d 5) is positive (CAP class >= 1).

**Involved allergens:** `["f75"]`

### 5. Alpha-Gal Syndrome

**Name:** `"Alpha-Gal Syndrome"`

**Condition:** Allergen with id `"o215"` (Alpha-Gal) is positive (CAP class >= 1).

**Involved allergens:** `["o215"]`

### 6. Mite-Shrimp Cross-Reactivity

**Name:** `"Mite-Shrimp Cross-Reactivity"`

**Condition:** A positive TROPOMYOSINS allergen from category `"MITES"` AND a positive TROPOMYOSINS allergen from category `"FOOD_SHELLFISH"`.

**Involved allergens:** The matching tropomyosin allergens from both categories.

### 7. Latex-Fruit Syndrome

**Name:** `"Latex-Fruit Syndrome"`

**Condition:** A positive allergen with id `"k220"` (Hev b 6.02) OR `"k224"` (Hev b 11) AND a positive allergen with source `"Kiwi"`.

**Involved allergens:** The matching latex allergen(s) and the kiwi allergen(s).

## Overall Risk

The `overall_risk` field is the maximum `risk_level` across all `allergen_results`, using the ordering: NEGLIGIBLE < LOW < MODERATE < HIGH < VERY_HIGH.
