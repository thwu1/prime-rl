#!/usr/bin/env python3
"""Write the bug report to /app/bugs_found.txt."""

report = """\
Bug 1 — CastVote missing vote-uniqueness guard
-----------------------------------------------
The CastVote action did not check whether the voter had already cast a vote
for another proposer (hasVotedFor[voter] = "none" was missing). This allowed
a single node to vote for multiple competing proposers, enabling two different
proposals to each accumulate a quorum and violate Agreement.

Fix: Added the guard  /\\ hasVotedFor[voter] = "none"  to CastVote.


Bug 2 — Decide uses insufficient vote threshold
------------------------------------------------
The Decide action required only  Cardinality(votes[n]) >= 1  instead of
>= Quorum (majority). With 3 nodes, Quorum = 2, but the buggy spec allowed
a proposer to decide with just its own self-vote (1 vote). Two proposers
could each self-decide different values, violating Agreement.

Fix: Changed the guard to  Cardinality(votes[n]) >= Quorum.


Bug 3 — Propose does not integrate with vote-tracking system
------------------------------------------------------------
The Propose action adds the proposer n to its own vote set (votes[n] \\cup {n})
— a self-vote — but has two defects in how it interacts with hasVotedFor:

(a) Missing guard: Propose does not check hasVotedFor[n] = "none", so a node
    that already voted for another proposer via CastVote can still propose.
    When it does, hasVotedFor[n] is overwritten from the old proposer to n,
    but the old vote in votes[old_proposer] still counts. This lets two
    competing proposals each reach quorum.

(b) Missing update: hasVotedFor[n] was listed in UNCHANGED, so after
    proposing, hasVotedFor[n] remains "none". The proposer can then
    CastVote for a competitor because the CastVote guard (after Bug 1 fix)
    checks hasVotedFor[voter] = "none" and it passes. The proposer effectively
    votes twice: once as self-vote during Propose, once via CastVote.

Fix: Added  /\\ hasVotedFor[n] = "none"  as a precondition to Propose, and
replaced UNCHANGED <<decided, hasVotedFor>> with
hasVotedFor' = [hasVotedFor EXCEPT ![n] = n] and UNCHANGED <<decided>>.
"""

with open("/app/bugs_found.txt", "w") as f:
    f.write(report)

print("Bug report written to /app/bugs_found.txt")
