A MARS (Memory Array Redcode Simulator) implementation exists at `/app/mars.py`. It is intended to faithfully implement the ICWS'94 Core War standard, but it contains multiple bugs that cause incorrect battle results.

Your task is to identify and fix all bugs in `/app/mars.py` so that the simulator produces correct results for all warrior matchups and parameter configurations.

The simulator accepts these command-line flags:

```
python3 /app/mars.py -s CORESIZE -c MAXCYCLES -p MAXPROCESSES -l MAXLENGTH -d MINDISTANCE -r ROUNDS -f warrior1.red warrior2.red
```

After all rounds, it prints one line per warrior: `FILENAME W L T` where W/L/T are win/loss/tie counts.

## Resources

- **ICWS'94 specification**: `/app/icws94_standard.txt` describes the complete execution semantics — addressing modes, modifiers, opcodes, and process scheduling. This is the authoritative reference for correct behavior.
- **Test warriors**: `/app/warriors/` contains warriors in Redcode load-file format exercising diverse instruction types, addressing modes, and strategies.
- **The simulator itself**: `/app/mars.py` can be imported as a Python module. The `MARS` class exposes `init_core()`, `load_warrior()`, and `execute()` for programmatic testing.