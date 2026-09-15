`/app/` contains a WebRTC signaling state machine (`/app/state_machine.py`) that simulates peer-to-peer calling between two peers via `/app/signaling_bus.py`. Supporting modules include `/app/protocol.py` (message types, peer states, SDP/ICE structures), `/app/media_engine.py` (media track simulation), and `/app/scenario.py` (call scenario helper). A reference legitimate call flow is at `/app/examples/legitimate_call.py`.

The system has a critical security invariant: **the callee's media tracks must never transmit until the callee explicitly calls `accept_call()`**. The implementation contains multiple vulnerabilities that violate this invariant through different attack vectors — an attacker who can inject signaling messages can force the callee to transmit audio/video without any user interaction.

Five proposed patches from different developers are at `/app/patches/patch_a.py` through `/app/patches/patch_e.py`. Each modifies `CallStateMachine` via its `apply(cls)` function. A helper at `/app/patches/apply_patch.py` can apply and reset patches. Some patches are effective, some fail to actually prevent the exploit they target, and some introduce regressions that break legitimate call flow.

Produce a complete security audit in `/app/analysis/` consisting of:

- **`state_graph.dot`** and **`state_graph.png`** — A Graphviz directed graph of the calling state machine covering all 7 `PeerState` values as nodes, with edges labeled by triggering message type or action, and vulnerable transitions visually distinguished. The PNG must be rendered from the DOT file.

- **`invariant_fuzzer.py`** — A Hypothesis `RuleBasedStateMachine` property-based fuzzer with `@rule` methods exercising signaling sequences (including adversarial ones) and an `@invariant` method asserting the callee never transmits without consent. Must include a `TestCase` attribute discoverable by pytest and must detect violations in the unpatched code.

- **`patch_verdicts.json`** — JSON array of 5 objects (one per patch) each with `patch_id`, `verdict` (`"effective"`, `"insufficient"`, or `"regression"`), and `reasoning`.

- **`report.json`** — JSON object with a `"vulnerabilities"` array where each entry includes `vulnerability_id`, `name`, `mechanism`, `affected_message_type`, and `impact`.