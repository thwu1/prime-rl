"""
Fix all five bugs in TwoPhase.tla, add the TPSafety invariant,
and complete TwoPhase.cfg.

Bug 1 (TMCommit): Guard 'tmPrepared # {}' allows the TM to commit after
       receiving just one Prepared message. Correct: 'tmPrepared = RM'.

Bug 2 (RMChooseToAbort): An aborting RM erroneously sends a Prepared
       message. Correct: UNCHANGED msgs.

Bug 3 (RMRcvCommitMsg): Guard accepts both Commit and Abort messages as
       triggers for committing. Correct: only Commit.

Bug 4 (TMAbort): Sends a Commit message instead of Abort.
       Correct: [type |-> "Abort"].

Bug 5 (TMRcvPrepared): Replaces tmPrepared with {rm} instead of adding
       to it. Correct: tmPrepared \\cup {rm}.
"""

# ---- Fix TwoPhase.tla ----

with open("/app/TwoPhase.tla", "r") as f:
    spec = f.read()

# Bug 1: TMCommit guard -- require ALL RMs prepared, not just any
spec = spec.replace(
    "  /\\ tmPrepared # {}",
    "  /\\ tmPrepared = RM",
)

# Bug 5: TMRcvPrepared -- accumulate instead of replace
spec = spec.replace(
    "  /\\ tmPrepared' = {rm}",
    "  /\\ tmPrepared' = tmPrepared \\cup {rm}",
)

# Bug 2: RMChooseToAbort -- remove spurious Prepared message send
old_abort = (
    'RMChooseToAbort(rm) ==\n'
    '  (*************************************************************************)\n'
    '  (* Resource manager rm spontaneously decides to abort.                   *)\n'
    '  (*************************************************************************)\n'
    '  /\\ rmState[rm] = "working"\n'
    '  /\\ rmState\' = [rmState EXCEPT ![rm] = "aborted"]\n'
    '  /\\ msgs\' = msgs \\cup {[type |-> "Prepared", rm |-> rm]}\n'
    '  /\\ UNCHANGED <<tmState, tmPrepared>>'
)
new_abort = (
    'RMChooseToAbort(rm) ==\n'
    '  (*************************************************************************)\n'
    '  (* Resource manager rm spontaneously decides to abort.                   *)\n'
    '  (*************************************************************************)\n'
    '  /\\ rmState[rm] = "working"\n'
    '  /\\ rmState\' = [rmState EXCEPT ![rm] = "aborted"]\n'
    '  /\\ UNCHANGED <<tmState, tmPrepared, msgs>>'
)
spec = spec.replace(old_abort, new_abort)

# Bug 3: RMRcvCommitMsg -- only accept Commit messages, not Abort
spec = spec.replace(
    '  /\\ [type |-> "Commit"] \\in msgs \\/ [type |-> "Abort"] \\in msgs',
    '  /\\ [type |-> "Commit"] \\in msgs',
)

# Bug 4: TMAbort -- send Abort message, not Commit
# Use surrounding context (tmState' = "aborted") to disambiguate from TMCommit
spec = spec.replace(
    '  /\\ tmState\' = "aborted"\n'
    '  /\\ msgs\' = msgs \\cup {[type |-> "Commit"]}',
    '  /\\ tmState\' = "aborted"\n'
    '  /\\ msgs\' = msgs \\cup {[type |-> "Abort"]}',
)

# ---- Add TPSafety invariant ----

tpsafety = (
    '\n'
    '(**************************************************************************)\n'
    '(* Safety strengthening: committed RMs imply TM committed and Commit msg. *)\n'
    '(**************************************************************************)\n'
    'TPSafety ==\n'
    '  \\A rm \\in RM : rmState[rm] = "committed" =>\n'
    '    /\\ tmState = "committed"\n'
    '    /\\ [type |-> "Commit"] \\in msgs\n'
)

# Insert TPSafety before TPInit
spec = spec.replace("TPInit ==", tpsafety + "\nTPInit ==")

with open("/app/TwoPhase.tla", "w") as f:
    f.write(spec)

# ---- Complete TwoPhase.cfg ----

with open("/app/TwoPhase.cfg", "r") as f:
    cfg = f.read()

if "TPConsistent" not in cfg:
    cfg = cfg.rstrip() + "\nINVARIANT TPConsistent\n"
if "TPSafety" not in cfg:
    cfg = cfg.rstrip() + "\nINVARIANT TPSafety\n"
if "CHECK_DEADLOCK" not in cfg:
    cfg = cfg.rstrip() + "\nCHECK_DEADLOCK FALSE\n"

with open("/app/TwoPhase.cfg", "w") as f:
    f.write(cfg)

print("Applied all fixes to TwoPhase.tla and TwoPhase.cfg")
