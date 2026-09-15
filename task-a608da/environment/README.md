# Conjecture-Style Property-Based Testing Framework

## Overview

This framework represents test cases as sequences of **typed choices**.
A test function draws choices from the sequence via `ConjectureData.draw_*()`
methods.  The five choice types are: integer, float, boolean, string, bytes.

## Key Concepts

### Choice Sequences

Every test case is fully determined by its choice sequence.
Manipulating the sequence (shrinking, reordering, deleting elements)
produces different test inputs.

### Shortlex Ordering

A total order on choice sequences: **shorter is always better**.
Among equal-length sequences, compare element-wise using
`choice_to_index`.  The shrinker's goal is to find the
**shortlex-minimal** "interesting" (bug-triggering) sequence.

### The Shrinker

The shrinker takes an interesting choice sequence and applies
**passes** to shrink it.  Each pass attempts a class of
transformations.  The recommended pass order is:

1. **Deletion** – remove contiguous groups of choices.
2. **Zeroing** – replace each choice with its type-specific zero
   (0, 0.0, False, `""`, `b""`), respecting constraints.
3. **Minimisation** – binary-search each choice toward zero.
4. **Reordering** – swap adjacent same-type choices when the later one
   is smaller under `choice_to_index`.
5. **Redistribution** – for adjacent integer pairs, redistribute value
   so one becomes zero (keeping the sum constant).

The main loop runs all passes repeatedly.  When a full cycle produces
no improvement, shrinking stops.

### The "Weird Loop" Pattern

In the **deletion** pass, a successful deletion changes the sequence
length.  After deleting at position *i*, the element that was at
*i + 1* shifts to *i*.  If you advance *i*, you skip it.

- On **success**: stay at *i*
- On **failure**: advance to *i + 1*

This pattern does **not** apply to replacement passes (zeroing,
minimisation), where the element stays in place regardless of outcome.

### The `consider` Method

`consider(candidate)` tries a candidate sequence:

1. Run the test function.
2. If the result is **INTERESTING** and the **drawn** choices have a
   strictly smaller `sort_key` than `self.current`, adopt them as the
   new best.
3. Return `True` if adopted, `False` otherwise.

**Important:** use the **drawn** choices (what the test actually
consumed), not the full candidate.  The test may draw fewer choices
than provided; using drawn choices automatically trims the surplus.

### Integer Binary Search

To minimise an integer choice, binary-search between its
*zero value* (`max(0, min_value)`) and its current value.
At each step try `mid = (lo + hi) // 2`.

### Float Minimisation

1. Try truncating to an integer (`math.trunc`).
2. Binary-search among integers between zero and the current integer
   part, same as the integer strategy.
