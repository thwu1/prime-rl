# seL4 Access Control Formal Specification Reference

This document defines the seL4 capability-based access control model as formalized
in the l4v (L4.verified) Isabelle/HOL proof repository. You must implement these
definitions faithfully to compute the authority graph.

## 1. Authority Types

The set of all authority types (called `auth` in the formal spec):

    auth = {Reset, Receive, SyncSend, Notify, Grant, Call, Reply, Control, DeleteDerived, Write}

`UNIV` denotes the set of ALL authority types (all 10 above).

## 2. Capability Rights

Capabilities carry a set of rights drawn from:

    cap_rights = {AllowRead, AllowWrite, AllowGrant, AllowGrantReply}

## 3. Rights-to-Authority Mapping

### 3.1 cap_rights_to_auth

    cap_rights_to_auth(rights, is_sync) =
        {Reset}
      ∪ (if AllowRead ∈ rights then {Receive} else {})
      ∪ (if AllowWrite ∈ rights then (if is_sync then {SyncSend} else {Notify}) else {})
      ∪ (if AllowGrant ∈ rights then UNIV else {})
      ∪ (if AllowGrantReply ∈ rights AND AllowWrite ∈ rights then {Call} else {})

### 3.2 reply_cap_rights_to_auth

    reply_cap_rights_to_auth(is_master, rights) =
        if AllowGrant ∈ rights OR is_master then UNIV else {Reply}

## 4. Per-Capability Authority Derivation

### 4.1 cap_auth_conferred(cap)

Returns the set of authority types conferred by holding a capability:

    cap_auth_conferred(cap) = case cap of
      NullCap                         → {}
      EndpointCap(obj, badge, rights) → cap_rights_to_auth(rights, is_sync=True)
      NotificationCap(obj, badge, rights) →
          cap_rights_to_auth(rights - {AllowGrant, AllowGrantReply}, is_sync=False)
          NOTE: NotificationCap STRIPS AllowGrant and AllowGrantReply from rights BEFORE
          computing auth. This is a critical subtlety.
      ReplyCap(obj, is_master, rights) → reply_cap_rights_to_auth(is_master, rights)
      CNodeCap(obj, bits, guard)      → {Control}
      ThreadCap(obj)                  → {Control}
      UntypedCap(dev, ptr, bits, idx) → {Control}
      DomainCap                       → {Control}
      IRQControlCap                   → {Control}
      IRQHandlerCap(irq)              → {Control}
      Zombie(ptr, bits, n)            → {Control}

### 4.2 obj_refs_ac(cap)

Returns the set of object references a capability applies to:

    obj_refs_ac(cap) = case cap of
      NullCap              → {}
      EndpointCap(obj,_,_) → {obj}
      NotificationCap(obj,_,_) → {obj}
      ReplyCap(obj,_,_)    → {obj}
      CNodeCap(obj,_,_)    → {obj}
      ThreadCap(obj)       → {obj}
      UntypedCap(_,_,_,_)  → {}    (authority comes via untyped_range instead)
      IRQControlCap        → {}
      IRQHandlerCap(_)     → {}
      Zombie(ptr,_,_)      → {ptr}
      DomainCap            → UNIV_OBJECTS  (all objects, special case)

## 5. Thread State Authority

### 5.1 tcb_st_to_auth(thread_state)

Returns a set of (object_ref, auth) pairs derived from the thread's blocking state:

    tcb_st_to_auth(state) = case state of
      BlockedOnNotification(ntfn) →
          {(ntfn, Receive)}

      BlockedOnSend(ep, payload) →
          {(ep, SyncSend)}
          ∪ (if payload.can_grant then {(ep, Grant), (ep, Call)} else {})
          ∪ (if payload.can_grant_reply then {(ep, Call)} else {})

      BlockedOnReceive(ep, payload) →
          {(ep, Receive)}
          ∪ (if payload.can_grant then {(ep, Grant)} else {})

      Running           → {}
      Inactive          → {}
      Restart           → {}
      BlockedOnReply    → {}
      IdleThreadState   → {}

## 6. Notification Binding Authority

If a thread `t` (labeled `l_t`) is bound to notification object `ntfn` (labeled `l_ntfn`):

    (l_t, Receive, l_ntfn) ∈ policy
    (l_t, Reset, l_ntfn) ∈ policy

## 7. Capability Transferability

A capability in a CDT child slot is "transferable" if:

    is_transferable(cap) = case cap of
      None (empty slot)                → True
      NullCap                          → True
      ReplyCap(_, master=False, _)     → True   (non-master reply cap)
      _                                → False

This distinction is critical for CDT authority derivation (Section 8.5-8.6).

## 8. State-to-Policy Rules (state_bits_to_policy)

These rules extract authority edges from the system state. Each edge is a triple
(source_label, auth_type, target_label) where labels are obtained via the
`pasObjectAbs` mapping (called `object_labels` in the system state JSON).

### 8.1 sbta_caps (Capability-derived authority)

For each capability slot (holder_obj, slot) containing cap:
  For each obj ∈ obj_refs_ac(cap):
    For each auth ∈ cap_auth_conferred(cap):
      Add edge: (label(holder_obj), auth, label(obj))

### 8.2 sbta_ts (Thread-state-derived authority)

For each thread tcb (labeled l_tcb):
  For each (obj_ref, auth) ∈ tcb_st_to_auth(tcb.state):
    Add edge: (l_tcb, auth, label(obj_ref))

### 8.3 sbta_bounds (Notification binding authority)

For each thread tcb (labeled l_tcb) bound to notification ntfn:
  Add edges: (l_tcb, Receive, label(ntfn)), (l_tcb, Reset, label(ntfn))

### 8.4 sbta_untyped (Untyped range authority)

For each UntypedCap(dev, ptr, bits, idx) held by holder (labeled l_holder):
  For each object obj_ref in range [ptr, ptr + 2^bits):
    Add edge: (l_holder, Control, label(obj_ref))

### 8.5 sbta_cdt (CDT Control authority — non-transferable only)

For each CDT entry where slot `parent` is the parent of slot `child`:
  If the capability in `child` is NOT transferable (is_transferable returns False):
    Add edge: (label(parent.object), Control, label(child.object))

### 8.6 sbta_cdt_transferable (CDT DeleteDerived authority — always)

For each CDT entry where slot `parent` is the parent of slot `child`:
  Add edge: (label(parent.object), DeleteDerived, label(child.object))

  NOTE: This edge is added regardless of transferability. The sbta_cdt rule
  (Control) is only added when NOT transferable. The sbta_cdt_transferable
  rule (DeleteDerived) is ALWAYS added.

## 9. Policy Wellformedness Closure

The `policy_wellformed` predicate is parameterized by a designated subject
(`pas_subject`). The authority graph must be closed under these rules. Apply
them iteratively until no new edges are added (fixed-point computation).

Let `agent` = pas_subject. Let `aag` = the current policy edge set.

### Rule 1 (Control reflexivity constraint)

    ∀agent'. (agent, Control, agent') ∈ aag → agent = agent'

This is a CONSTRAINT, not a generator. The agent (pas_subject) may only have
Control authority over its own label. If your computation generates
(agent, Control, other), the system is not wellformed.

### Rule 2 (Agent self-authority)

    ∀auth_type. (agent, auth_type, agent) ∈ aag

The designated subject has ALL authority types over itself. Add these edges
to the initial policy before closure. This applies ONLY to the designated
subject, not to all subjects.

### Rule 3 (Grant + Receive → mutual Control)

    ∀s, r, ep.
      (s, Grant, ep) ∈ aag ∧ (r, Receive, ep) ∈ aag
      → (s, Control, r) ∈ aag ∧ (r, Control, s) ∈ aag

If subject `s` has Grant authority to label `ep`, and subject `r` has Receive
authority to the SAME label `ep`, then `s` and `r` gain mutual Control.

### Rule 4 (IRQ notification forwarding — conditional)

    maySendIrqs ∧ irq ∈ irqs ∧ (irq_label, Notify, ntfn_label) ∈ aag
    → (agent, Notify, ntfn_label) ∈ aag

Only applies when maySendIrqs is True.

### Rule 5 (Call implies SyncSend)

    ∀s, ep. (s, Call, ep) ∈ aag → (s, SyncSend, ep) ∈ aag

### Rule 6 (Call + Receive → Reply)

    ∀s, r, ep.
      (s, Call, ep) ∈ aag ∧ (r, Receive, ep) ∈ aag
      → (r, Reply, s) ∈ aag

If subject `s` can Call endpoint label `ep`, and subject `r` can Receive on
the same label `ep`, then `r` gains Reply authority over `s`.

### Rule 7 (Reply → DeleteDerived)

    ∀s, r. (s, Reply, r) ∈ aag → (r, DeleteDerived, s) ∈ aag

### Rule 8 (DeleteDerived transitivity)

    ∀l1, l2, l3.
      (l1, DeleteDerived, l2) ∈ aag ∧ (l2, DeleteDerived, l3) ∈ aag
      → (l1, DeleteDerived, l3) ∈ aag

### Rule 9 (Call + Receive + Grant → mutual Control)

    ∀s, r, ep.
      (s, Call, ep) ∈ aag ∧ (r, Receive, ep) ∈ aag ∧ (r, Grant, ep) ∈ aag
      → (s, Control, r) ∈ aag ∧ (r, Control, s) ∈ aag

## 10. Output Format

Write `/app/results.json` with the following structure:

```json
{
  "authority_graph": {
    "<src_label>": {
      "<dst_label>": ["<auth1>", "<auth2>", ...]
    }
  },
  "query_results": {
    "<query_id>": <result>
  }
}
```

Rules:
- Authority type lists must be sorted alphabetically
- Only include (src, dst) pairs with non-empty authority sets
- Include all subjects that appear as source in at least one edge
- Query result types:
  - "authority_set": sorted list of auth type strings
  - "who_has_auth": sorted list of subject labels
  - "wellformed_check": boolean (true if Rule 1 is satisfied)
  - "dd_reachable": boolean (true if a DeleteDerived path exists from source to target)
