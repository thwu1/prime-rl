A Sokoban tournament database at `/app/sokoban.db` stores four puzzle levels in a normalized relational schema where individual cells are typed records rather than plaintext grids. The database schema can be inspected directly.

Per-level constraints (maximum pushes, maximum moves) are in `/app/config.json`.

Solve all four levels. A solution is a string of direction characters (`u`/`d`/`l`/`r`, case-insensitive) encoding sequential player moves from the initial position to a state where every box rests on a goal cell. All moves must be legal: no walking through walls, and pushing a box requires its destination cell to be free of walls and other boxes.

Insert each solution into the database's `solutions` table with accurate metadata (inspect the table definition for required columns). Then execute `/app/tools/validate.sh` to generate a passing validation report at `/app/report.json`.

Each level contains 6 boxes. All four levels must pass validation.