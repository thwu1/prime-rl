
//! Concurrent editing trace replayer using a simplified Yjs-style sequence CRDT.
//!
//! Each inserted character carries a unique (agent, seq) identity and records
//! the identities of its left and right neighbours at insertion time (origin_left,
//! origin_right).  The integration function resolves concurrent inserts by
//! scanning between origin neighbours and tie-breaking on agent index (lower =
//! leftward).  Deletions are tracked as a set of deleted item-ids; double
//! deletes across branches are therefore automatically idempotent.

use std::collections::HashSet;
use std::env;
use std::fs;

use serde::Deserialize;
use serde_json::Value;

// ---------------------------------------------------------------------------
// Domain types
// ---------------------------------------------------------------------------

/// Unique identity for an inserted character: (agent_index, sequence_number).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord)]
struct ItemId(usize, usize);

/// A single character in the CRDT list.
#[derive(Clone, Debug)]
struct CrdtItem {
    id: ItemId,
    /// Identity of the visible character immediately left of this one at
    /// insertion time, or `None` if inserted at the document start.
    origin_left: Option<ItemId>,
    /// Identity of the visible character immediately right of this one at
    /// insertion time, or `None` if inserted at the document end.
    origin_right: Option<ItemId>,
    content: char,
}

/// Document state: an ordered list of CRDT items plus a set of deleted ids.
#[derive(Clone, Debug, Default)]
struct Doc {
    items: Vec<CrdtItem>,
    deleted: HashSet<ItemId>,
}

// ---------------------------------------------------------------------------
// JSON trace format
// ---------------------------------------------------------------------------

#[derive(Deserialize)]
struct Trace {
    #[serde(rename = "numAgents")]
    num_agents: usize,
    txns: Vec<Txn>,
}

#[derive(Deserialize)]
struct Txn {
    parents: Vec<usize>,
    agent: usize,
    patches: Vec<Value>,
}

// ---------------------------------------------------------------------------
// Doc implementation
// ---------------------------------------------------------------------------

impl Doc {
    fn new() -> Self {
        Self::default()
    }

    /// Linear scan for the position of `id` in `self.items`.
    fn find_idx(&self, id: &ItemId) -> Option<usize> {
        self.items.iter().position(|it| it.id == *id)
    }

    /// Conceptual position of an origin_left reference (-1 for None/start).
    fn left_pos(&self, ol: &Option<ItemId>) -> isize {
        match ol {
            None => -1,
            Some(id) => self.find_idx(id).expect("origin_left missing") as isize,
        }
    }

    /// Conceptual position of an origin_right reference (items.len() for None/end).
    fn right_pos(&self, or_ref: &Option<ItemId>) -> usize {
        match or_ref {
            None => self.items.len(),
            Some(id) => self.find_idx(id).expect("origin_right missing"),
        }
    }

    /// Integrate a new item into the CRDT-ordered list using Yjs-style rules.
    ///
    /// Scanning proceeds between origin_left (exclusive) and origin_right
    /// (exclusive).  Among concurrent peers in that range:
    ///
    /// - **Same origin_left, same origin_right**: lower `ItemId` wins (placed
    ///   leftward).
    /// - **Same origin_left, different origin_right**: the item whose
    ///   origin_right is further LEFT (narrower scope) is placed first.
    /// - **Different origin_left**: if the other item's origin_left is further
    ///   LEFT (broader context) we insert before it; if further RIGHT (it
    ///   belongs to a subsequent chain) we skip past it.
    fn integrate(&mut self, new_item: CrdtItem) {
        let left_bound = match new_item.origin_left {
            Some(ref id) => self.find_idx(id).expect("origin_left not found") + 1,
            None => 0,
        };
        let right_bound = match new_item.origin_right {
            Some(ref id) => self.find_idx(id).expect("origin_right not found"),
            None => self.items.len(),
        };

        let mut insert_pos = left_bound;
        let mut i = left_bound;

        // Scanning state for the Yjs algorithm.
        let mut scanning = false;
        let mut scan_pos = left_bound;

        while i < right_bound {
            let other_ol = self.items[i].origin_left;
            let other_or = self.items[i].origin_right;
            let other_id = self.items[i].id;

            if other_ol == new_item.origin_left {
                // Same origin_left.
                if other_or == new_item.origin_right {
                    // Same origin_right — tie-break by ItemId (lower agent wins).
                    if new_item.id < other_id {
                        break;
                    }
                    scanning = false;
                } else {
                    // Different origin_right — compare positions.
                    let my_or_pos = self.right_pos(&new_item.origin_right);
                    let other_or_pos = self.right_pos(&other_or);

                    if other_or_pos < my_or_pos {
                        // Other has narrower scope → goes first.  Enter
                        // scanning mode so we remember this position.
                        if !scanning {
                            scanning = true;
                            scan_pos = i + 1;
                        }
                    } else {
                        scanning = false;
                    }
                }
            } else {
                // Different origin_left.
                let my_ol_pos = self.left_pos(&new_item.origin_left);
                let other_ol_pos = self.left_pos(&other_ol);

                if other_ol_pos < my_ol_pos {
                    // Other has broader context → insert before it.
                    break;
                }
                // Other's origin_left is further right (part of a chain) → skip.
            }

            insert_pos = i + 1;
            i += 1;
        }

        if scanning {
            insert_pos = scan_pos;
        }

        self.items.insert(insert_pos, new_item);
    }

    /// Return the ids of currently visible (non-deleted) items in order.
    fn visible_ids(&self) -> Vec<ItemId> {
        self.items
            .iter()
            .filter(|it| !self.deleted.contains(&it.id))
            .map(|it| it.id)
            .collect()
    }

    /// Render the visible document text.
    fn to_text(&self) -> String {
        self.items
            .iter()
            .filter(|it| !self.deleted.contains(&it.id))
            .map(|it| it.content)
            .collect()
    }
}

// ---------------------------------------------------------------------------
// Trace processing
// ---------------------------------------------------------------------------

/// Operations generated by a single transaction's patches.
struct TxnOps {
    inserts: Vec<CrdtItem>,
    deletes: Vec<ItemId>,
}

/// Parse a JSON patch value into (position, delete_count, insert_string).
fn parse_patch(val: &Value) -> (usize, usize, String) {
    let arr = val.as_array().expect("patch must be a JSON array");
    let pos = arr[0].as_u64().expect("patch[0] must be integer") as usize;
    let del = arr[1].as_u64().expect("patch[1] must be integer") as usize;
    let ins = if arr.len() > 2 {
        arr[2].as_str().unwrap_or("").to_string()
    } else {
        String::new()
    };
    (pos, del, ins)
}

/// Compute the transitive ancestor set (excluding self) for every transaction.
fn compute_ancestors(txns: &[Txn]) -> Vec<HashSet<usize>> {
    let mut result: Vec<HashSet<usize>> = Vec::with_capacity(txns.len());
    for txn in txns {
        let mut ancs = HashSet::new();
        for &p in &txn.parents {
            ancs.insert(p);
            // Merge parent's ancestors.
            for &a in &result[p] {
                ancs.insert(a);
            }
        }
        result.push(ancs);
    }
    result
}

/// Replay an entire trace and return the final document text.
fn replay(trace: &Trace) -> String {
    let mut agent_seqs: Vec<usize> = vec![0; trace.num_agents];
    let mut all_ops: Vec<TxnOps> = Vec::with_capacity(trace.txns.len());
    let ancestors = compute_ancestors(&trace.txns);

    for (txn_idx, txn) in trace.txns.iter().enumerate() {
        // ------------------------------------------------------------------
        // 1. Reconstruct the document state visible to this transaction by
        //    integrating all items from ancestor transactions.
        // ------------------------------------------------------------------
        let ancs = &ancestors[txn_idx];
        let mut sorted_ancs: Vec<usize> = ancs.iter().copied().collect();
        sorted_ancs.sort_unstable();

        let mut doc = Doc::new();
        for &anc in &sorted_ancs {
            for item in &all_ops[anc].inserts {
                doc.integrate(item.clone());
            }
            for &del_id in &all_ops[anc].deletes {
                doc.deleted.insert(del_id);
            }
        }

        // ------------------------------------------------------------------
        // 2. Convert each position-based patch to CRDT operations.
        // ------------------------------------------------------------------
        let mut new_inserts: Vec<CrdtItem> = Vec::new();
        let mut new_deletes: Vec<ItemId> = Vec::new();

        for patch_val in &txn.patches {
            let (pos, del_len, ins_content) = parse_patch(patch_val);
            let visible = doc.visible_ids();

            // Determine the origin neighbours for new characters.
            let origin_left = if pos > 0 {
                Some(visible[pos - 1])
            } else {
                None
            };
            let origin_right = if pos + del_len < visible.len() {
                Some(visible[pos + del_len])
            } else {
                None
            };

            // Apply deletions.
            for i in 0..del_len {
                let id = visible[pos + i];
                doc.deleted.insert(id);
                new_deletes.push(id);
            }

            // Apply insertions character by character.
            let mut prev_left = origin_left;
            for ch in ins_content.chars() {
                let id = ItemId(txn.agent, agent_seqs[txn.agent]);
                agent_seqs[txn.agent] += 1;
                let item = CrdtItem {
                    id,
                    origin_left: prev_left,
                    origin_right,
                    content: ch,
                };
                doc.integrate(item.clone());
                new_inserts.push(item);
                prev_left = Some(id);
            }
        }

        all_ops.push(TxnOps {
            inserts: new_inserts,
            deletes: new_deletes,
        });
    }

    // ------------------------------------------------------------------
    // 3. Build the final document from the union of all operations.
    // ------------------------------------------------------------------
    let mut doc = Doc::new();
    for ops in &all_ops {
        for item in &ops.inserts {
            doc.integrate(item.clone());
        }
        for &del_id in &ops.deletes {
            doc.deleted.insert(del_id);
        }
    }
    doc.to_text()
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("Usage: {} <trace.json>", args[0]);
        std::process::exit(1);
    }

    let content = fs::read_to_string(&args[1]).expect("failed to read trace file");
    let trace: Trace = serde_json::from_str(&content).expect("failed to parse trace JSON");
    let result = replay(&trace);
    print!("{}", result);
}
