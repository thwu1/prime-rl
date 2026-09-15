A latency-critical service uses the hash table at `/app/hashmap.c`. The implementation compiles and passes the smoke test (`cd /app && make && ./hashmap_test`), but it fails the production qualification suite.

Diagnose the deficiencies in the current implementation and rewrite `/app/hashmap.c` so that every test in the qualification suite passes. Do not modify `/app/hashmap.h`, `/app/main.c`, or `/app/Makefile`.

The header `/app/hashmap.h` is the authoritative API contract — all constants, struct fields, and function signatures must be honored exactly.