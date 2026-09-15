
# Log Template Post-Processing Correction Rules

## Overview

Log templates produced by parsers often contain artifacts that reduce accuracy: uncollapsed digit sequences, partially-replaced variable tokens, or redundant wildcard patterns. The following correction pipeline normalizes templates to improve evaluation accuracy.

The wildcard token `<*>` represents a variable part of the log template.

## Delimiter Sets

**Token delimiters** (used for tokenization — split while preserving delimiters):

    whitespace  ,  !  ;  :  =  |  "  '  [  ]  (  )  {  }  .  -  +  @  #  $  %  &

When splitting, use a capturing group so delimiter tokens are preserved in the output list. For example, splitting `"host:10.0.0.1"` yields `["host", ":", "10", ".", "0", ".", "0", ".", "1"]`.

**Note:** The forward slash `/` is intentionally NOT a delimiter. Tokens may contain slashes.

## Correction Rules (apply in this order)

### Rule 1: Double Space (DS)

Strip leading and trailing whitespace from the template, then collapse all runs of consecutive whitespace into a single space.

### Rule 2: Tokenize

Split the template string by the token delimiter set above, preserving delimiters as separate tokens. This produces an ordered list of tokens (content tokens and delimiter tokens interleaved).

### Rule 3: Digit (DG)

For each content token: if the token consists entirely of digit characters (matches the pattern `^\d+$`), replace the entire token with `<*>`.

### Rule 4: Word-Variable (WV)

For each content token: if the token satisfies ALL of:
- It contains the substring `<*>` 
- It is not exactly equal to `<*>` (i.e., it has additional characters)
- It does not contain whitespace or forward-slash characters

Then replace the entire token with `<*>`.

**Examples:** `node<*>` → `<*>`, `error<*>_fatal` → `<*>`, `<*>_count` → `<*>`. But `<*>` alone stays `<*>`.

**Special case:** The token `<*>/<*>` should NOT be collapsed by WV (it is handled by later rules).

### Rule 5: Reassemble

Join all tokens (content and delimiter) back into a single template string.

### Rule 6: Dot-Variable (DV)

Repeatedly replace the pattern `<*>.<*>` with `<*>` until no further replacements occur.

### Rule 7: Consecutive-Variable (CV)

Repeatedly replace the pattern `<*><*>` (two adjacent wildcards with no separator) with `<*>` until no further replacements occur.

### Rule 8: Additional Separator Collapses

Apply each of the following string replacements repeatedly until convergence (no more matches). Process them in order, and re-check each rule until stable:

1. ` #<*># ` → ` <*> `  (space-hash-wildcard-hash-space)
2. ` #<*> ` → ` <*> `
3. `<*>:<*>` → `<*>`
4. `<*>#<*>` → `<*>`
5. `<*>/<*>` → `<*>`
6. `<*>@<*>` → `<*>`
7. `<*>.<*>` → `<*>`  (safety re-check of DV)
8. ` "<*>" ` → ` <*> `  (space-quote-wildcard-quote-space)
9. ` '<*>' ` → ` <*> `  (space-apostrophe-wildcard-apostrophe-space)
10. `<*><*>` → `<*>`  (safety re-check of CV)

## Examples

| Input | Output | Rules Applied |
|-------|--------|---------------|
| `Error    in   component  ` | `Error in component` | DS |
| `Block 42 at step 7` | `Block <*> at step <*>` | DG |
| `node<*>_status` | `<*>` | WV |
| `<*>.<*>.<*>.<*>` | `<*>` | DV |
| `src <*>:<*> dest <*>:<*>` | `src <*> dest <*>` | Additional (rule 3) |
| `Path <*>/<*>/<*>` | `Path <*>` | Additional (rule 5) |
| `user<*>@host<*>` | `<*>` | WV then Additional (rule 6) |
| `host 10.251.73.220` | `host <*>` | DG then DV |
