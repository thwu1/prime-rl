`/app/tournament.trf` contains a 16-player Swiss chess tournament after 4 completed rounds in FIDE Tournament Report Format (TRF). The SQLite database `/app/players.db` holds authoritative tournament metadata (table `tournament_meta`), player details (table `players`), and organizer-imposed pairing restrictions (table `forbidden_pairs`). The TRF conversion utility `trf2json` is installed (see `trf2json --help`); `jq` and `sqlite3` are also available.

**Caution:** The TRF file's `XXR` header line contains an incorrect total-rounds value. The authoritative round count, current round number, and initial colour must be obtained from the `tournament_meta` table in the SQLite database. Any rows in `forbidden_pairs` represent additional absolute pairing constraints beyond C1.

Compute the correct Round 5 pairing under FIDE Dutch System rules (C.04.3, effective 1 February 2026) and write the result to `/app/round5_pairing.json`.

Output format — a JSON object conforming to `/app/output_schema.json`:
- `"pairings"`: list of `{"white": <TPN>, "black": <TPN>}` sorted by higher-ranked player's score descending then TPN ascending.
- `"bye"`: TPN of the PAB recipient, or `null`.

The engine must comply with all FIDE Dutch System rules: absolute criteria C1-C3, completion criterion C4, PAB criterion C5, quality criteria C6-C21 in priority order, bracket processing with S1/S2 subgroup splitting (transpositions and exchanges per Articles 3-4), heterogeneous bracket logic (MDPs, limbo, remainders), and colour allocation per Article 5.