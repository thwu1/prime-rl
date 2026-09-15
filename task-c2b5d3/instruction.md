Five job shop scheduling problem (JSP) instances from the OR-Library benchmark collection are provided in `/app/data/`. Each file uses the standard OR-Library format: the first line contains the number of jobs and machines; each subsequent line describes one job as alternating (machine-number, processing-time) pairs for its operations in order.

Build a solver that reads all five instances, computes feasible schedules that minimize makespan, and writes results to `/app/results.json`.

## Output format

`/app/results.json` must contain a JSON object keyed by instance name (filename without `.txt`):

```
{
  "<instance>": {
    "makespan": <int>,
    "schedule": {
      "<job_index>": [
        {"machine": <int>, "start": <int>, "duration": <int>},
        ...
      ],
      ...
    }
  },
  ...
}
```

Instance names: `ft06`, `ft10`, `ft20`, `la01`, `abz7`.

## Feasibility requirements

- Operations within each job follow the given precedence order with no time overlap
- No two operations overlap on the same machine
- Each operation runs on its designated machine with its specified processing time
- All start times are non-negative integers

## Makespan targets

| Instance | Size (jobs x machines) | Max makespan |
|----------|----------------------|-------------|
| ft06     | 6 x 6               | 60          |
| la01     | 10 x 5              | 750         |
| ft10     | 10 x 10             | 1080        |
| ft20     | 20 x 5              | 1350        |
| abz7     | 20 x 15             | 900         |

Achieving these targets requires an optimization approach beyond simple dispatching heuristics — consider metaheuristics (simulated annealing, genetic algorithms, tabu search) or constraint programming.