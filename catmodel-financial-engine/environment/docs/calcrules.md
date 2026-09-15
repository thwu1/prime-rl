# FM Calculation Rules (calcrule) Specification

This document specifies the financial module calculation rules. Each rule is
identified by a `calcrule_id` and uses a subset of profile fields.

## Profile Fields

| Short | Full name     |
|-------|---------------|
| d1    | deductible_1  |
| d2    | deductible_2  |
| d3    | deductible_3  |
| a1    | attachment_1  |
| l1    | limit_1       |
| sh1   | share_1       |
| sh2   | share_2       |
| sh3   | share_3       |

## Rules

In all pseudocode below, `x.loss` is the aggregated input loss for the node.

### calcrule 1 — Deductible and limit

Required fields: d1, l1

```
loss = x.loss - deductible_1
if loss < 0 then loss = 0
if loss > limit_1 then loss = limit_1
```

### calcrule 2 — Deductible, attachment, limit, and share

Required fields: d1, a1, l1, sh1

```
loss = x.loss - deductible_1
if loss < 0 then loss = 0
if loss > (attachment_1 + limit_1) then
    loss = limit_1
else
    loss = loss - attachment_1
if loss < 0 then loss = 0
loss = loss * share_1
```

### calcrule 3 — Franchise deductible and limit

Required fields: d1, l1

A franchise deductible means the full loss passes through once
the threshold is exceeded; losses at or below the threshold produce zero.

```
if x.loss <= deductible_1 then loss = 0
else loss = x.loss
if loss > limit_1 then loss = limit_1
```

### calcrule 4 — Deductible as percentage of TIV and limit

Required fields: d1, l1

Note: In practice, `deductible_1` is pre-converted to an absolute
monetary amount based on Total Insured Value before the FM engine
runs. This rule then behaves identically to calcrule 1.

```
loss = x.loss - deductible_1
if loss < 0 then loss = 0
if loss > limit_1 then loss = limit_1
```

### calcrule 5 — Deductible and limit as a proportion of loss

Required fields: d1, l1

Both the deductible and the limit are expressed as proportions of the
input loss value itself.

```
effective_deductible = x.loss * deductible_1
effective_limit = x.loss * limit_1

if (deductible_1 + limit_1) >= 1 then
    loss = x.loss - effective_deductible
else
    loss = effective_limit
```

When `deductible_1 + limit_1 >= 1`, the effective limit is never binding
so only the proportional deductible applies. When the sum is less than 1,
the limit always binds, producing `x.loss * limit_1`.

### calcrule 6 — Deductible as percentage of TIV (no limit)

Required fields: d1

Pre-converted to absolute amount; behaves as calcrule 12.

```
loss = x.loss - deductible_1
if loss < 0 then loss = 0
```

### calcrule 9 — Limit with deductible as a proportion of limit

Required fields: d1, l1

The deductible is expressed as a fraction of the limit, then applied
as a monetary deductible.

```
effective_deductible = deductible_1 * limit_1
loss = x.loss - effective_deductible
if loss < 0 then loss = 0
if loss > limit_1 then loss = limit_1
```

### calcrule 12 — Deductible only

Required fields: d1

```
loss = x.loss - deductible_1
if loss < 0 then loss = 0
```

### calcrule 14 — Limit only

Required fields: l1

```
loss = x.loss
if loss > limit_1 then loss = limit_1
```

### calcrule 16 — Deductible as a proportion of loss

Required fields: d1

The deductible is a percentage of the input loss.

```
loss = x.loss - (x.loss * deductible_1)
if loss < 0 then loss = 0
```

### calcrule 20 — Reverse franchise deductible

Required fields: d1

Opposite of the franchise: pays only when the loss is at or below the
deductible threshold. Above the threshold, nothing is paid.

```
if x.loss > deductible_1 then loss = 0
else loss = x.loss
```

### calcrule 100 — Pass-through (do nothing)

No fields required.

```
loss = x.loss
```
