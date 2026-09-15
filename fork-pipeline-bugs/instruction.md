`/app/pipeline.c` implements a parallel data processing pipeline. It forks worker processes that each compute a partial sum and a hash-chain checksum over a partition of integer data from `/app/data/numbers.txt`. Results are collected through both a pipe and a shared memory region for cross-validation, and a verification report is written to an output file.

Build: `make -C /app`
Usage: `/app/pipeline /app/data/numbers.txt /app/output.txt <num_workers>`

The program compiles cleanly but fails at runtime. Diagnose and fix all issues in `/app/pipeline.c`.

The corrected program must produce the following output format for any worker count from 1 to 8, complete within 15 seconds, exit with code 0, and leave no zombie processes:

```
PIPELINE workers=N datasize=M
W0: sum=<partial_sum> checksum=<hash_chain> state=DONE
W1: sum=<partial_sum> checksum=<hash_chain> state=DONE
...
TOTAL: <aggregate_sum>
CHECKSUM_VERIFY: OK
SUM_VERIFY: OK
PROGRESS: N/N DONE
```

Partial sums, checksums, and the aggregate total must be numerically correct for the given data partitioning (array divided into N chunks by integer division, last worker handles remainder). The computation functions are defined in `/app/compute.h`.