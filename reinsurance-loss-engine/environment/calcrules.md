# Financial Module Specification

## Financial Structure Files

The financial module reads four CSV files from the programme directory:

### fm_programme.csv
Columns: `from_agg_id`, `level_id`, `to_agg_id`
Defines item-to-aggregate grouping across processing levels.

### fm_profile.csv
Columns: `policytc_id`, `calcrule_id`, `deductible_1`, `deductible_2`, `deductible_3`, `attachment_1`, `limit_1`, `share_1`, `share_2`, `share_3`
Maps each policy terms combination to a calculation rule and its parameters.

### fm_policytc.csv
Columns: `layer_id`, `level_id`, `agg_id`, `policytc_id`
Associates policy terms profiles with aggregate IDs at each level and layer.

### fm_xref.csv
Columns: `output_id`, `agg_id`, `layer_id`
Cross-reference mapping from aggregate/layer pairs to output identifiers.

## Calculation Rules Reference

Each calcrule operates on an input loss `x` and produces an output loss using fields from `fm_profile.csv`.

### Fields

| Short | Full Name      | Description                      |
|-------|----------------|----------------------------------|
| d1    | deductible_1   | Primary deductible               |
| d2    | deductible_2   | Secondary deductible (minimum)   |
| d3    | deductible_3   | Tertiary deductible (maximum)    |
| a1    | attachment_1   | Attachment point / excess        |
| l1    | limit_1        | Limit                            |
| sh1   | share_1        | Primary share proportion         |
| sh2   | share_2        | Secondary share (placement %)    |
| sh3   | share_3        | Tertiary share                   |

### Rules

#### calcrule_id = 100: Pass-through
```
output = x
```

#### calcrule_id = 1: Deductible and limit
```
output = x - d1
if output < 0: output = 0
if output > l1: output = l1
```

#### calcrule_id = 2: Deductible, attachment, limit, and share
```
output = x - d1
if output < 0: output = 0
if output > a1 + l1:
    output = l1
else:
    output = output - a1
if output < 0: output = 0
output = output * sh1
```

#### calcrule_id = 3: Franchise deductible and limit
```
if x <= d1: output = 0
elif x <= l1: output = x
else: output = l1
```
Note: Franchise means no deduction from the loss if the threshold is exceeded.

#### calcrule_id = 5: Deductible and limit as proportion of loss
```
output = x - x * d1
if output > x * l1: output = x * l1
```

#### calcrule_id = 12: Deductible only
```
output = x - d1
if output < 0: output = 0
```

#### calcrule_id = 14: Limit only
```
if x <= l1: output = x
else: output = l1
```

#### calcrule_id = 16: Deductible as proportion of loss
```
output = x * (1 - d1)
```

#### calcrule_id = 20: Reverse franchise deductible
```
if x > d1: output = 0
else: output = x
```
Note: Pays only if loss is at or below the threshold.

#### calcrule_id = 22: Reinsurance % ceded, limit, and % placed
```
if sh1 == 0: output = 0
else:
    pre_share_limit = l1 / sh1
    all_share = sh1 * sh2 * sh3
    max_output = l1 * sh2 * sh3
    if x <= pre_share_limit: output = x * all_share
    else: output = max_output
```

#### calcrule_id = 24: Reinsurance excess terms
```
if sh1 == 0: output = 0
else:
    pre_att = a1 / sh1
    pre_att_lim = (l1 + a1) / sh1
    att_share = a1 * sh2 * sh3
    all_share = sh1 * sh2 * sh3
    max_output = l1 * sh2 * sh3
    if x <= pre_att: output = 0
    elif x <= pre_att_lim: output = x * all_share - att_share
    else: output = max_output
```

#### calcrule_id = 25: Reinsurance proportional terms
```
output = x * sh1 * sh2 * sh3
```
