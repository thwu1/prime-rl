The project at `/app/` contains an incomplete concurrent program verification framework in Java. Source code is under `/app/src/`, with `Main.java` (default package) as the entry point and a `Makefile` for building.

`/app/src/modelchecker/ModelChecker.java` is a stub. Implement its `check(ConcurrentProgram)` method to perform exhaustive state-space exploration of the given concurrent program, detecting deadlocks, data races, and assertion failures, and returning a `CheckerResult` with all found violations and exploration statistics.

The project contains build and framework defects beyond the stub that will prevent correct compilation or produce incorrect results. These must be diagnosed and fixed.

Build and run commands: `make compile`, `make run`, `make run-por`.

Stdout format per program:

    PROGRAM: <name>
    STATES: <count>
    TRANSITIONS: <count>
    VIOLATIONS: <count>
    VIOLATION: <TYPE>: <message>
    ---

`VIOLATION` lines appear only when violations exist. Violation types: `DEADLOCK`, `DATA_RACE`, `ASSERTION_FAILURE`.

Required results for all seven programs defined in `/app/src/programs/Programs.java`:

- `DiningPhilosophers`: must contain `DEADLOCK`
- `SimpleRace`: must contain `DATA_RACE`
- `MutualExclusion`: exactly zero violations
- `RaceCounter`: must contain `DATA_RACE`
- `LockOrderDeadlock`: must contain `DEADLOCK`
- `HighOrderRace`: must contain `ASSERTION_FAILURE`; must NOT contain `DATA_RACE`
- `ReentrantMutex`: exactly zero violations

Every program must report positive `STATES` and `TRANSITIONS` counts.

When invoked with `--por` (partial-order reduction): the set of violation types reported for each program must be identical to the non-POR run, and `DiningPhilosophers` must have strictly fewer explored states than without `--por`.
