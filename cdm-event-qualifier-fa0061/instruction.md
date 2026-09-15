Implement a Java CLI tool at `/app/src/cdm/EventQualifier.java` that classifies ISDA CDM (Common Domain Model) BusinessEvent JSON documents into their correct lifecycle event type according to CDM event qualification semantics.

When compiled and executed as:

```
javac -cp "/app/lib/*" -d /app/build /app/src/cdm/EventQualifier.java
java -cp "/app/build:/app/lib/*" cdm.EventQualifier /app/events/<event>.json
```

it must print exactly one qualifier string to stdout (e.g. `Novation`) with no other stdout output. Exit code must be 0 on success. Place any dependency jars in `/app/lib/`.

Ten CDM BusinessEvent JSON files reside in `/app/events/`. Each encodes a distinct OTC derivatives trade lifecycle event conforming to the CDM JSON serialization format. The tool must correctly classify all ten, plus any structurally conforming CDM BusinessEvent not in that set.

**Required qualifiers** (each event maps to exactly one, and all ten are represented across the event files): `Novation`, `PartialNovation`, `Allocation`, `ClearedTrade`, `Termination`, `PartialTermination`, `Increase`, `Execution`, `ContractFormation`, `Compression`.

Classification must be derived entirely from the structural content of each JSON document by analyzing instruction primitives, intent fields, before/after trade state transitions, counterparty references, trade identifiers, quantity changes, party roles, and closed-state presence. The tool must produce the correct qualifier regardless of the input filename or specific data values (party names, amounts, dates). Do not rely on filenames, file ordering, content hashing, file sizes, or any mapping files to determine the result.

A stub implementation exists at `/app/src/cdm/EventQualifier.java`. Internet access is available for downloading dependencies and consulting CDM documentation.
