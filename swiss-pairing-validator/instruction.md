The SQLite database `/app/tournament.db` stores the complete state of a 16-player Swiss chess tournament ("Zephyr Invitational 2026") through 4 completed rounds. Three tables:

- `tournament_info` — name, city, country, dates, time control, rounds, initial colour rule, arbiters
- `players` — starting rank (TPN), sex, title, name, rating, federation, FIDE ID, birth date, score, rank
- `round_results` — per-round outcomes: opponent TPN, colour, result (`1`/`=`/`0`)

Five candidate pairing sets for Round 5 are in `/app/candidates.json`, each a list of 8 pairs `[white_starting_rank, black_starting_rank]`.

Produce two outputs:

**1. `/app/tournament.trf`** — A valid FIDE TRF (Tournament Report File) reconstructed from the database. Must include all data-identification lines (`012`, `022`, `032`, `042`, `052`, `062`, `072`, `082`, `092`, `102`, `112`, `122`, `132`, `XXR`, `XXC`) and one `001` line per player with correct fixed-width positioning for starting rank, sex+title, name (33 chars), rating, federation, FIDE ID, birth date, total score, rank, and per-round opponent/colour/result blocks (each exactly 10 characters wide).

**2. `/app/audit_result.json`** — Audit each candidate pairing for compliance with the FIDE Dutch System rules (Handbook C.04.3). Write a JSON array of five objects (indexed 0–4), each containing:

- `"candidate_index"`: integer 0–4
- `"c1"`: C1 violations (rematches)
- `"c3"`: C3 violations (non-topscorer pair sharing absolute colour preference)
- `"colour_allocation_errors"`: boards violating the Article 5.2 colour allocation cascade
- `"c12"`: colour preference denials
- `"c13"`: strong/absolute colour preference denials
- `"c14"`: repeat downfloat violations
- `"c15"`: repeat upfloat-opponent violations
- `"legal"`: true only if c1 == 0 and c3 == 0
- `"quality_penalty"`: c12 + c13 + c14 + c15