A computational linguistics research team's fieldwork database at `/data/fieldwork.db` (SQLite) contains lexical data, field observations, training examples, and test cases for three underdocumented numeral systems — Turahi, Belago, and Renshi — from the Vorathi language family. Supplementary linguistic metadata is in `/data/metadata.json`.

The database was contaminated during digitization of handwritten field notes: some training entries contain transcription errors where the recorded word form does not correctly encode the listed number. The `confidence` metadata field does not reliably indicate corruption.

Analyze the numeral systems, identify all corrupted training entries, and process the test cases. Produce the following files in `/app/output/`:

- **`errors.json`** — JSON array of corrupted training entries, each with fields: `id` (row ID from `training` table), `language`, `number`, `wrong_word`, `correct_word`. Sorted by `id`.
- **`fix.sql`** — SQL `UPDATE` statements to correct each corrupted entry's `word_form` in the `training` table.
- **`decode_results.tsv`** — Tab-separated: `language`, `word_form`, `decoded_number` — one row per `test_decode` entry, ordered by table ID.
- **`encode_results.tsv`** — Tab-separated: `language`, `number`, `encoded_word_form` — one row per `test_encode` entry, ordered by table ID.
- **`cross_results.tsv`** — Tab-separated: `source_language`, `source_word`, `target_language`, `target_word` — one row per `test_cross` entry, ordered by table ID.

All encoded word forms must match the canonical representation used in the non-corrupted training data.