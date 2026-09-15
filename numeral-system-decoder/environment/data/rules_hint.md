# Numeral Systems Documentation

You have been provided with training data from three different numeral systems used by fictional language communities. Your task is to analyze the training data, reverse-engineer the rules of each numeral system, and build a program that can decode, encode, and cross-translate between them.

## General Information

Each system uses a different base (radix) for counting. The three systems are:

- **Turahi**: A straightforward system with a single consistent base and named powers.
- **Belago**: Uses a primary base with intermediate sub-groupings for composing digits. Contains special grouping words for sub-units.
- **Renshi**: Uses a base with a special morphological process for expressing certain digit values as complements.

## Structural Hints

1. In all three systems, when a word for a smaller quantity appears immediately before a word for a larger unit, the values are **multiplied**. When a larger unit appears before a smaller quantity, the values are **added**. Numbers are composed from largest to smallest component.

2. The Belago system has named "pivot" words for its base and higher powers. These pivots separate multiplier groups from additive remainders. The sub-groupings within each multiplier or remainder follow the same additive principle with their own sub-unit words.

3. In the Renshi system, some digit words share a common morphological prefix with existing basic digit words. Discovering the relationship between these prefixed forms and the basic digits is essential to understanding the full system.

4. When a base or power word appears with no explicit multiplier before it, the multiplier is implicitly 1.

## Output Format

Produce three tab-separated output files in `/app/output/`:

- **`decode_results.tsv`**: One row per decode test entry. Columns: `system`, `word_form`, `decoded_number`
- **`encode_results.tsv`**: One row per encode test entry. Columns: `system`, `number`, `encoded_word_form`
- **`cross_results.tsv`**: One row per cross-system test entry. Columns: `source_system`, `source_word`, `target_system`, `target_word_form`

All entries must exactly match the canonical encoding for each system (the same encoding convention used in the training data).
