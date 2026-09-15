# HSM Engine Reference

## 1. Overview

A Hierarchical State Machine (HSM) extends flat state machines with state
nesting: states can contain substates. Events are processed by the innermost
(current) state first; unhandled events propagate upward to ancestor states.
Transitions between states at different hierarchy levels require executing
exit and entry actions in the correct order.

## 2. State Handler Protocol

Every state is a function `HsmRet handler(Hsm *me, const HsmEvent *e)`.

The engine communicates with state handlers via **reserved signals**:

| Signal          | Purpose | Expected handler behavior |
|-----------------|---------|---------------------------|
| `HSM_EMPTY_SIG` | Query superstate | Return `HSM_SUPER(parent)` (from default case) |
| `HSM_ENTRY_SIG` | Enter this state | Execute entry actions, return `HSM_HANDLED()` |
| `HSM_EXIT_SIG`  | Exit this state  | Execute exit actions, return `HSM_HANDLED()` |
| `HSM_INIT_SIG`  | Initial transition | Return `HSM_TRAN(substate)` or `HSM_SUPER(parent)` if none |

For **user signals**, a handler may:
- `HSM_HANDLED()` -- event processed, no state change (internal transition)
- `HSM_TRAN(target)` -- take a state transition to `target`
- `HSM_UNHANDLED()` -- guard condition failed; the engine should try the
  event in the parent state (semantically distinct from `HSM_SUPER`)
- Fall through to `default: return HSM_SUPER(parent)` -- event not recognized

The `HSM_SUPER(parent)` macro sets `me->temp` to `parent` and returns
`HSM_RET_SUPER`. The `HSM_TRAN(target)` macro sets `me->temp` to `target`
and returns `HSM_RET_TRAN`. The `HSM_UNHANDLED()` macro returns
`HSM_RET_UNHANDLED` without modifying `me->temp`.

**Finding a state's superstate:** Dispatch `HSM_EMPTY_SIG` to any state
handler. Its `default` case will return `HSM_SUPER(parent)`, placing the
parent handler pointer in `me->temp`.

**Important:** Dispatching `HSM_EXIT_SIG` to a state that handles it
explicitly (returning `HSM_HANDLED`) does NOT set `me->temp`. In that case,
you must separately dispatch `HSM_EMPTY_SIG` if you need the superstate.
If `HSM_EXIT_SIG` was not handled (fell through to `default`), `me->temp`
is already set to the superstate.

## 3. Invariants

- After `hsm_init()` or `hsm_dispatch()`, `me->state` must be a leaf state
  (no pending initial transitions).
- State nesting must not exceed `HSM_MAX_NEST_DEPTH`.
- The top state (`hsm_top`) always returns `HSM_RET_IGNORED`.
- Every state handler's `default` case must return `HSM_SUPER(parent)`.
- A self-transition (source == target) must exit and re-enter the state.
