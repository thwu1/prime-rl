# TTCN-3 Conformance Test Execution Semantics Reference

Based on ETSI ES 201 873-1 (TTCN-3 Core Language) and ES 201 873-4 (Operational Semantics).

## Test Suite Definition Format (JSON-IR)

Each test suite JSON file contains:

```
{
  "suite_name": "...",
  "registry": { "<template_name>": <template_def>, ... },
  "sut_responses": { "<msg_key>": <response_or_null>, ... },
  "test_cases": [ <test_case>, ... ]
}
```

### Registry

Maps template names to template definitions. Templates follow the matching
engine's format (see `/app/matcher.py`). Templates can reference other templates
via the `modifies` mechanism.

### SUT Responses

Maps message keys to the System Under Test's deterministic response:
- A dict: the SUT's response message
- `null`: the SUT does not respond (triggers timeout)
- A list of dicts: a sequence of responses delivered one at a time (used with `repeat` in alt blocks; the first element is delivered immediately, subsequent elements are delivered on each `repeat`)

### Test Case

```
{
  "id": "...",
  "description": "...",
  "pics_expr": "<boolean expression>",
  "group": "...",
  "components": { "<component_id>": {}, ... },
  "timers": { "<timer_name>": <duration_float>, ... },
  "behavior": {
    "<component_id>": [ <op>, ... ],
    ...
  }
}
```

## PICS Boolean Expressions

Protocol Implementation Conformance Statements (PICS) determine which test
cases apply to a given SUT implementation. The `pics_expr` field contains a
boolean expression over PICS capability identifiers.

### Syntax

```
expr     := or_expr
or_expr  := and_expr ("OR" and_expr)*
and_expr := not_expr ("AND" not_expr)*
not_expr := "NOT" not_expr | primary
primary  := IDENTIFIER | "(" expr ")"
```

Operator precedence (highest first): NOT, AND, OR.

### Examples

- `"PICS_SIP_REG"` — true if capability PICS_SIP_REG is declared
- `"PICS_A AND PICS_B"` — conjunction
- `"PICS_A AND (PICS_B OR PICS_C)"` — OR with grouping
- `"PICS_A AND NOT PICS_B"` — negation
- `""` or absent — always true (test case always applies)

### Evaluation

Look up each IDENTIFIER in the PICS profile's `capabilities` dict.
Missing identifiers evaluate to `false`.

## Behavior Operations

### send

```json
{"op": "send", "msg_key": "<key>"}
```

Look up `sut_responses[msg_key]` to get the SUT's response:
- If `null`: no response available (causes timeout alternatives to match)
- If a single dict: set as the pending response for this component
- If a list: set the first element as pending response; queue remaining elements for delivery on `repeat`

### start_timer / stop_timer

```json
{"op": "start_timer", "name": "<timer_name>"}
{"op": "stop_timer", "name": "<timer_name>"}
```

Start or stop a named timer. Timer durations are defined in the test case's
`timers` section. In the simulation model, timers are used to determine whether
timeout alternatives should fire.

### setverdict

```json
{"op": "setverdict", "v": "<verdict>"}
```

Set the component's local verdict. Verdicts follow strict monotonic ordering:

    none(0) < pass(1) < inconc(2) < fail(3) < error(4)

A verdict can only increase, never decrease. Setting "pass" after "fail" keeps
the verdict at "fail".

### alt

```json
{"op": "alt", "alts": [ <alternative>, ... ]}
```

Evaluate alternatives in order (first-match semantics). Each alternative has a
guard and a body:

#### Receive guard

```json
{
  "guard": "receive",
  "template_ref": "<registry_template_name>",
  "body": [ <op>, ... ]
}
```
or with inline template:
```json
{
  "guard": "receive",
  "template": { ... },
  "body": [ <op>, ... ]
}
```

Matches if the component has a pending response (not null) AND the response
matches the template. Use `/app/matcher.py`'s `match()` function with the
suite's registry for template resolution.

On match: clear the pending response, execute the body.

#### Timeout guard

```json
{
  "guard": "timeout",
  "timer": "<timer_name>",
  "body": [ <op>, ... ]
}
```

Matches when the SUT did not respond (pending response is null), indicating the
simulated timer has expired.

#### Else guard

```json
{
  "guard": "else",
  "body": [ <op>, ... ]
}
```

Always matches if no previous alternative matched.

### repeat

```json
{"op": "repeat"}
```

Can only appear inside an alt body. Causes the enclosing alt block to be
re-evaluated from the top. If the SUT response was a sequence (list), advance
to the next response in the queue before re-evaluating.

Use bounded iteration (e.g., max 20 cycles) to prevent infinite loops.

### sync

```json
{"op": "sync", "point": "<sync_point_name>"}
```

Synchronization point for multi-component test cases. In sequential simulation
mode, this is a no-op (components execute sequentially, not concurrently).

## Parallel Test Components

Test cases may define multiple components in the `components` field. Each
component has independent:
- Verdict state (starts at "none")
- Timer state
- Pending response state

Execute each component's behavior sequence. The test case verdict is the
maximum of all component verdicts.

## Template Resolution

When an alt guard specifies `template_ref`, look up the named template in the
suite's `registry`. The template may use `modifies` (template inheritance)
which is resolved by the matcher. Always pass the registry to `match()`.

## Verdict Aggregation

### Test case verdict
Maximum of all component verdicts for that test case.

### Suite verdict
Maximum of all test case verdicts within the suite.

### Overall verdict
Maximum of all suite verdicts across all suites.

## ConformanceEngine Interface

Your `/app/engine.py` must export a `ConformanceEngine` class:

```python
class ConformanceEngine:
    def __init__(self, pics_config):
        """Initialize with PICS profile dict containing 'capabilities' key."""
        ...

    def execute_suite(self, suite_def):
        """Execute a test suite definition and return results.

        Args:
            suite_def: Parsed JSON test suite definition

        Returns:
            dict with keys:
                suite_name: str
                total: int (total test cases in suite)
                selected: int (test cases selected by PICS)
                skipped: list[str] (IDs of test cases skipped by PICS)
                results: list[dict] (each: {id: str, verdict: str, group: str})
                suite_verdict: str
        """
        ...
```

## Report Format

`/app/run_conformance.py` produces one report per PICS profile:

```json
{
  "profile": "<profile_name>",
  "suites": [
    {
      "suite_name": "...",
      "total": 7,
      "selected": 5,
      "skipped": ["TC_ID_1", "TC_ID_2"],
      "results": [
        {"id": "TC_ID_3", "verdict": "pass", "group": "..."},
        ...
      ],
      "suite_verdict": "fail"
    }
  ],
  "overall_verdict": "fail"
}
```
