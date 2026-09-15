Implement a fully functional ICWS'94 Memory Array Redcode Simulator (MARS) in Python at `/app/mars.py`. Your simulator must produce battle results consistent with pMARS, the reference ICWS'94 simulator compiled and available at `/usr/local/bin/pmars`.

The ICWS'94 specification is at `/app/spec/icws94.txt`. Example warrior load files are in `/app/warriors/`. Use pMARS as an oracle during development to verify your implementation's correctness — it can assemble warriors, run battles with deterministic positioning, and report win/loss/tie outcomes.

Your `/app/mars.py` module must expose a `MARS` class with this interface:

- `MARS(core_size=8000, max_processes=8000, max_cycles=80000)` — Initialize the simulator. Core is filled with `DAT.F $0, $0`.
- `load_warrior(filepath, position=None)` — Parse an ICWS'94 load file and load the warrior into core at the given position (default 0). Handle `ORG` and `END` directives for setting the execution start offset. Convert negative field values to modular positives. Return a warrior ID (0-indexed).
- `run()` — Execute the battle to completion. Return `{'winner': int_or_None, 'cycles': int}`. Winner is the surviving warrior's ID, or `None` for a tie. Warriors execute in load order (warrior 0 first each cycle).
- `step()` — Execute one cycle (one instruction per living warrior). Return `True` if the battle should continue, `False` if over.
- `get_cell(position)` — Return a dict `{'opcode': str, 'modifier': str, 'a_mode': str, 'a_number': int, 'b_mode': str, 'b_number': int}` for the instruction at the given core position. Opcodes/modifiers are uppercase strings; modes are single characters.
- `get_process_count(warrior_id)` — Return the number of active processes for the given warrior.

The simulator must correctly implement all 17 ICWS'94 opcodes (DAT, MOV, ADD, SUB, MUL, DIV, MOD, JMP, JMZ, JMN, DJN, CMP/SEQ, SNE, SLT, SPL, NOP), all 7 instruction modifiers (.A, .B, .AB, .BA, .F, .X, .I), all 8 addressing modes (immediate `#`, direct `$`, A-indirect `*`, B-indirect `@`, A-predecrement `{`, B-predecrement `<`, A-postincrement `}`, B-postincrement `>`), FIFO process queues with correct SPL semantics (queue PC+1 first, then split target), modular arithmetic throughout, division/modulo by zero handling (process terminated, unaffected fields unchanged), and default ICWS'88-to-'94 modifier assignment when no modifier is present in the load file.