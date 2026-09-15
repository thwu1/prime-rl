#!/usr/bin/env python3
"""
Fix the 3 bugs in VotingProtocol.tla by reading the original spec
and applying targeted, semantically meaningful patches.

Bug 1 (CastVote): Missing guard that prevents a node from voting for
       multiple proposers. Must check hasVotedFor[voter] = "none".

Bug 2 (Decide): Insufficient vote threshold — uses >= 1 instead of
       >= Quorum, letting a proposer decide with only its own self-vote.

Bug 3 (Propose): The self-vote (adding n to votes[n]) neither checks
       hasVotedFor[n] = "none" nor sets hasVotedFor[n] = n. This has
       two consequences: (a) a node that already voted via CastVote can
       still propose, overwriting its hasVotedFor; (b) a proposer's
       hasVotedFor stays "none", letting it CastVote for a competitor.
       Both parts must be fixed.
"""

import sys

spec_path = "/app/VotingProtocol.tla"

with open(spec_path, "r") as f:
    content = f.read()

original = content

# ── Bug 1 fix: add hasVotedFor guard to CastVote ──────────────────
old_castvote = (
    "    /\\ voter \\notin votes[proposer]\n"
    "    /\\ votes' = [votes EXCEPT ![proposer] = votes[proposer] \\cup {voter}]"
)
new_castvote = (
    "    /\\ voter \\notin votes[proposer]\n"
    "    /\\ hasVotedFor[voter] = \"none\"\n"
    "    /\\ votes' = [votes EXCEPT ![proposer] = votes[proposer] \\cup {voter}]"
)
content = content.replace(old_castvote, new_castvote, 1)

# ── Bug 2 fix: require quorum in Decide ───────────────────────────
content = content.replace(
    "/\\ Cardinality(votes[n]) >= 1",
    "/\\ Cardinality(votes[n]) >= Quorum",
    1,
)

# ── Bug 3 fix (part a): Propose must guard hasVotedFor[n] = "none" ─
# A node that already voted via CastVote must not be able to propose
# (which would overwrite its hasVotedFor and effectively double-vote).
content = content.replace(
    "    /\\ decided[n] = \"none\"\n"
    "    /\\ proposed' = [proposed EXCEPT ![n] = v]",
    "    /\\ decided[n] = \"none\"\n"
    "    /\\ hasVotedFor[n] = \"none\"\n"
    "    /\\ proposed' = [proposed EXCEPT ![n] = v]",
    1,
)

# ── Bug 3 fix (part b): Propose must set hasVotedFor[n] = n ───────
# The self-vote must be tracked so the proposer cannot later CastVote
# for a competing proposer.
content = content.replace(
    "    /\\ UNCHANGED <<decided, hasVotedFor>>",
    "    /\\ hasVotedFor' = [hasVotedFor EXCEPT ![n] = n]\n"
    "    /\\ UNCHANGED <<decided>>",
    1,
)

if content == original:
    print("ERROR: no substitutions were applied", file=sys.stderr)
    sys.exit(1)

with open(spec_path, "w") as f:
    f.write(content)

print("Applied 3 fixes to VotingProtocol.tla")
