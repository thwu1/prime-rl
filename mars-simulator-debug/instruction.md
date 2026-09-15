Five opponent warriors occupy an ICWS'94 Core War hill at `/app/opponents/`. Each represents a different competitive strategy archetype. The pMARS simulator (compiled with `-DEXT94 -DPERMUTATE -DRWLIMIT`) is installed at `/usr/local/bin/pmars`.

Analyze the opponents, evaluate their strategic interactions (which strategies counter which), and design a single warrior that performs well against the entire field. Write your warrior to `/app/challenger.red` as valid ICWS'94 Redcode with at most 100 instructions.

**Evaluation parameters** (per matchup: 200 rounds, core size 8000, max processes 8000, max cycles 80000, warrior 2 fixed at position 4000):

- The challenger must win at least 1 round against **each** opponent individually
- The challenger must not lose more than 80% of rounds against any single opponent (i.e., wins + ties >= 40 for each matchup)
- The challenger must accumulate at least 200 total wins across all 5 matchups combined (out of 1000 total rounds)