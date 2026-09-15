`/app/blockht.c` contains a skeleton for a dynamically-resizing hash table that packs variable-length key-value records into fixed-size blocks. Struct definitions, constants, helper utilities, and a hash function are already implemented. The public API contract is in `/app/blockht.h`.

Implement all stub functions in `/app/blockht.c` so that `make -C /app` produces a correct `/app/libblockht.so`.

The skeleton's internal structures, field names, and provided helper functions fully specify the intended design. Every field in `BlockHashTable` and every helper exists for a reason — together they define the algorithm you must implement. Study them to determine how the pieces compose into a working system. The relationship between the struct fields and the slot-computation helper encodes the table's resizing strategy; the record-layout types and block helpers encode the storage strategy. Your implementation must be consistent with all of these.

The tests validate exact behavioral invariants including expansion timing, update-versus-insert semantics, statistics consistency, and data integrity across tens of thousands of records. Passing all tests requires getting subtle ordering and bookkeeping details correct.

Do not modify `/app/blockht.h` or `/app/Makefile`.