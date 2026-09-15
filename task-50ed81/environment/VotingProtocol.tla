---- MODULE VotingProtocol ----
\* A voting-based consensus protocol for distributed agreement.
\* Nodes propose values, collect votes, and decide when sufficient support exists.
\*
\* Safety property: Agreement - all decided values must be the same.

EXTENDS Integers, FiniteSets

CONSTANTS
    Nodes,   \* Set of participating nodes
    Values   \* Set of proposable values

VARIABLES
    proposed,     \* proposed[n] - value proposed by node n, or "none"
    votes,        \* votes[n] - set of nodes that voted for n's proposal
    decided,      \* decided[n] - value decided by node n, or "none"
    hasVotedFor   \* hasVotedFor[n] - which node n cast its vote for, or "none"

vars == <<proposed, votes, decided, hasVotedFor>>

\* A quorum requires a strict majority of nodes
Quorum == (Cardinality(Nodes) \div 2) + 1

\* Type correctness invariant
TypeOK ==
    /\ proposed \in [Nodes -> Values \cup {"none"}]
    /\ votes \in [Nodes -> SUBSET Nodes]
    /\ decided \in [Nodes -> Values \cup {"none"}]
    /\ hasVotedFor \in [Nodes -> Nodes \cup {"none"}]

\* Initial state: nothing proposed, no votes cast, nothing decided
Init ==
    /\ proposed = [n \in Nodes |-> "none"]
    /\ votes = [n \in Nodes |-> {}]
    /\ decided = [n \in Nodes |-> "none"]
    /\ hasVotedFor = [n \in Nodes |-> "none"]

\* Node n proposes value v and includes itself in its own voter set
Propose(n, v) ==
    /\ proposed[n] = "none"
    /\ decided[n] = "none"
    /\ proposed' = [proposed EXCEPT ![n] = v]
    /\ votes' = [votes EXCEPT ![n] = votes[n] \cup {n}]
    /\ UNCHANGED <<decided, hasVotedFor>>

\* Node 'voter' casts a vote supporting 'proposer'
CastVote(voter, proposer) ==
    /\ proposed[proposer] # "none"
    /\ voter # proposer
    /\ voter \notin votes[proposer]
    /\ votes' = [votes EXCEPT ![proposer] = votes[proposer] \cup {voter}]
    /\ hasVotedFor' = [hasVotedFor EXCEPT ![voter] = proposer]
    /\ UNCHANGED <<proposed, decided>>

\* Node n decides on its proposed value when it has gathered enough support
Decide(n) ==
    /\ proposed[n] # "none"
    /\ decided[n] = "none"
    /\ Cardinality(votes[n]) >= 1
    /\ decided' = [decided EXCEPT ![n] = proposed[n]]
    /\ UNCHANGED <<proposed, votes, hasVotedFor>>

\* Next-state relation
Next ==
    \/ \E n \in Nodes, v \in Values : Propose(n, v)
    \/ \E voter, proposer \in Nodes : CastVote(voter, proposer)
    \/ \E n \in Nodes : Decide(n)

\* Full specification with stuttering
Spec == Init /\ [][Next]_vars

\* Safety: Agreement - if any two nodes have decided, they decided the same value
Agreement ==
    \A n1, n2 \in Nodes :
        (decided[n1] # "none" /\ decided[n2] # "none")
        => (decided[n1] = decided[n2])

====
