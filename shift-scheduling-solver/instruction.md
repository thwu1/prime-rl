Solve the instance in `/app/instance.json`. Assign one shift per employee per day over `num_weeks * 7` days, minimizing total penalty. Shifts: 0=Off, 1=Morning, 2=Afternoon, 3=Night. Day `d` has weekday `d % 7` (0=Mon, 6=Sun).

## Hard Constraints

- **Skills:** Employee `e` may only work shifts in `skills[e]`.
- **Fixed:** Each `[e, s, d]` in `fixed_assignments` is immutable.
- **Forbidden transitions:** `[prev, next, 0]` in `penalized_transitions` forbids `prev` on day `d` then `next` on `d+1`.
- **Sequence bounds:** `shift_constraints` entry `[shift, hard_min, _, _, _, hard_max, _]` bounds every maximal contiguous run of `shift` to `[hard_min, hard_max]`.
- **Weekly sum bounds:** `weekly_sum_constraints` entry (same format) bounds per-week count of `shift`.
- **Incompatible nights:** Pairs in `incompatible_night_pairs` cannot both work Night on the same day.
- **Weekend completeness:** If true, each employee is Off on Saturday iff Off on Sunday per week.
- **Coverage:** Per department, per working shift s in {1,2,3}, per day: workers from that department must meet `weekly_cover_demands[dept][day_of_week][s-1]`.

## Soft Penalties (objective)

Each `shift_constraints` entry is `[shift, hard_min, soft_min, min_cost, soft_max, hard_max, max_cost]`:
- Run length `L < soft_min` adds `min_cost*(soft_min-L)`; `L > soft_max` adds `max_cost*(L-soft_max)`.

`weekly_sum_constraints` uses the same format; count below/above soft bounds penalized analogously.

`penalized_transitions` entry `[prev, next, cost]` with `cost > 0`: each occurrence adds `cost`.

Coverage excess: workers above demand times `excess_cover_penalties[s-1]`.

Requests `[e, s, d, weight]`: adds `weight` when employee `e` gets shift `s` on day `d` (negative weight = reward).

## Output

Write `/app/output.json` with keys `objective` (int: total penalty), `schedule` (dict mapping employee string id to list of shift indices per day), and `status` ("OPTIMAL" or "FEASIBLE"). Write your solver as `/app/solver.py`.