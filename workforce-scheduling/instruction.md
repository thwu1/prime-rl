A hospital needs an optimal 4-week (28-day) shift schedule for 10 employees across 4 shift types: Off (O), Day (D), Evening (E), Night (N). The complete problem specification is in `/app/problem.json`.

Write a Python program at `/app/solver.py` that reads `/app/problem.json`, builds and solves a constraint optimization model using the CP-SAT solver from Google OR-Tools (pre-installed), and writes the solution to `/app/schedule.json`.

The problem includes:

- **Staffing demands**: minimum employees per shift per day-of-week, with penalties for excess staffing beyond the minimum
- **Employee skills**: 4 of 10 employees are senior-qualified; the Day shift requires at least one senior each day
- **Fixed assignments**: pre-scheduled shifts and vacation days that cannot be changed
- **Shift sequence constraints**: hard and soft bounds on consecutive days working the same shift type (e.g., max 4 consecutive night shifts, max 5 consecutive off days); penalties accrue per excess/deficit day beyond soft bounds
- **Weekly sum constraints**: hard and soft bounds on total shifts of each type per employee per week
- **Forbidden transitions**: Night followed by Day on consecutive days is prohibited
- **Penalized transitions**: Evening followed by Night is allowed but incurs a penalty
- **Employee preferences**: weighted requests for or against specific shift assignments (negative weight = preference, positive = avoidance)
- **Incompatibility pairs**: two employee pairs cannot both be assigned to the same specified shift type on the same day
- **Weekend pairing**: penalty when an employee has exactly one of Saturday/Sunday off
- **Night fairness**: penalty proportional to the range (max minus min) of total night shifts across all employees, encouraging equitable distribution

The objective is to minimize total penalty from all soft constraints. All hard constraints must be strictly satisfied. The total penalty must be at most 500.

Output format for `/app/schedule.json`:
```json
{
  "schedule": [
    ["O", "D", "E", ...],
    ...
  ],
  "objective": <number>
}
```
where `schedule[e][d]` is the shift assignment for employee `e` on day `d`, and `objective` is the total penalty value.