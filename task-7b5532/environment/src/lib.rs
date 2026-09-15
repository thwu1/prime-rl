
//! Incremental relational query engine with sorted relations and multi-way join.

use std::cell::RefCell;
use std::cmp::Ordering;
use std::rc::Rc;

// ============================================================
// Relation: sorted, deduplicated tuple collection
// ============================================================

pub struct Relation<Tuple: Ord> {
    pub elements: Vec<Tuple>,
}

impl<Tuple: Ord> Relation<Tuple> {
    pub fn new(mut elements: Vec<Tuple>) -> Self {
        elements.sort();
        elements.dedup();
        Relation { elements }
    }

    pub fn is_empty(&self) -> bool {
        self.elements.is_empty()
    }

    pub fn len(&self) -> usize {
        self.elements.len()
    }

    pub fn merge(self, other: Self) -> Self {
        let mut elements = Vec::with_capacity(self.elements.len() + other.elements.len());
        elements.extend(self.elements);
        elements.extend(other.elements);
        Self::new(elements)
    }
}

impl<Tuple: Ord> From<Vec<Tuple>> for Relation<Tuple> {
    fn from(vec: Vec<Tuple>) -> Self {
        Self::new(vec)
    }
}

// ============================================================
// Gallop: exponential + binary hybrid search on sorted slices
// ============================================================

/// Advances through `slice` while `cmp` returns true, using exponential
/// doubling then binary narrowing. Returns the suffix starting at the
/// first element where `cmp` is false.
pub fn gallop<T>(mut slice: &[T], mut cmp: impl FnMut(&T) -> bool) -> &[T] {
    if !slice.is_empty() && cmp(&slice[0]) {
        let mut step = 1;
        while step < slice.len() && cmp(&slice[step]) {
            slice = &slice[step..];
            step <<= 1;
        }
        step >>= 1;
        while step > 0 {
            if step < slice.len() && cmp(&slice[step]) {
                slice = &slice[step..];
            }
            step >>= 1;
        }
        slice = &slice[1..]; // advance past last true element
    }
    slice
}

// ============================================================
// Variable: incrementally-maintained relation
// ============================================================

pub struct Variable<Tuple: Ord> {
    stable: Rc<RefCell<Vec<Relation<Tuple>>>>,
    recent: Rc<RefCell<Relation<Tuple>>>,
    to_add: Rc<RefCell<Vec<Relation<Tuple>>>>,
}

impl<Tuple: Ord + Clone> Variable<Tuple> {
    pub fn new() -> Self {
        Variable {
            stable: Rc::new(RefCell::new(Vec::new())),
            recent: Rc::new(RefCell::new(Relation::new(Vec::new()))),
            to_add: Rc::new(RefCell::new(Vec::new())),
        }
    }

    /// Queue a relation for future admission.
    pub fn insert(&self, relation: Relation<Tuple>) {
        if !relation.is_empty() {
            self.to_add.borrow_mut().push(relation);
        }
    }

    /// Cycle data through tiers:
    ///   1. recent → stable (with geometric doubling)
    ///   2. to_add → recent (deduplicated against stable)
    /// Returns true iff recent is non-empty after cycling.
    pub fn changed(&self) -> bool {
        // Step 1: merge recent into stable with geometric batching
        let recent = std::mem::replace(
            &mut *self.recent.borrow_mut(),
            Relation::new(Vec::new()),
        );
        if !recent.is_empty() {
            let mut stable = self.stable.borrow_mut();
            let mut batch = recent;
            while stable
                .last()
                .map(|x| x.len() <= 2 * batch.len())
                == Some(true)
            {
                let last = stable.pop().unwrap();
                batch = batch.merge(last);
            }
            stable.push(batch);
        }

        // Step 2: promote to_add → recent, dedup against stable
        let mut to_add_ref = self.to_add.borrow_mut();
        if let Some(mut to_add_rel) = to_add_ref.pop() {
            while let Some(more) = to_add_ref.pop() {
                to_add_rel = to_add_rel.merge(more);
            }
            drop(to_add_ref);

            // Remove elements already present in any stable batch
            let stable = self.stable.borrow();
            for batch in stable.iter() {
                let mut slice = &batch.elements[..];
                to_add_rel.elements.retain(|x| {
                    slice = gallop(slice, |y| y < x);
                    slice.is_empty() || &slice[0] != x
                });
            }
            drop(stable);

            *self.recent.borrow_mut() = to_add_rel;
        } else {
            drop(to_add_ref);
        }

        !self.recent.borrow().is_empty()
    }

    /// Collect all tuples across all tiers.
    pub fn complete(&self) -> Vec<Tuple> {
        let mut result = Vec::new();
        for batch in self.stable.borrow().iter() {
            result.extend(batch.elements.iter().cloned());
        }
        result.extend(self.recent.borrow().elements.iter().cloned());
        result.sort();
        result.dedup();
        result
    }
}

// ============================================================
// Binary join helpers
// ============================================================

/// Merge-join two sorted key-value relations, calling `result` on matches.
pub fn join_helper<Key: Ord, Val1: Ord, Val2: Ord>(
    input1: &Relation<(Key, Val1)>,
    input2: &Relation<(Key, Val2)>,
    mut result: impl FnMut(&Key, &Val1, &Val2),
) {
    let mut slice1 = &input1.elements[..];
    let mut slice2 = &input2.elements[..];

    while !slice1.is_empty() && !slice2.is_empty() {
        match slice1[0].0.cmp(&slice2[0].0) {
            Ordering::Less => {
                slice1 = gallop(slice1, |x| x.0 < slice2[0].0);
            }
            Ordering::Equal => {
                let count1 = slice1
                    .iter()
                    .take_while(|x| x.0 == slice1[0].0)
                    .count();
                let count2 = slice2
                    .iter()
                    .take_while(|x| x.0 == slice2[0].0)
                    .count();
                for i1 in 0..count1 {
                    for i2 in 0..count2 {
                        result(&slice1[0].0, &slice1[i1].1, &slice2[i2].1);
                    }
                }
                slice1 = &slice1[count1..];
                slice2 = &slice2[count2..];
            }
            Ordering::Greater => {
                slice2 = gallop(slice2, |x| x.0 < slice1[0].0);
            }
        }
    }
}

/// Semi-naive binary equijoin between two incremental variables.
pub fn join_into<Key, Val1, Val2, Result>(
    input1: &Variable<(Key, Val1)>,
    input2: &Variable<(Key, Val2)>,
    output: &Variable<Result>,
    mut logic: impl FnMut(&Key, &Val1, &Val2) -> Result,
) where
    Key: Ord + Clone,
    Val1: Ord + Clone,
    Val2: Ord + Clone,
    Result: Ord + Clone,
{
    let mut results = Vec::new();

    let recent1 = input1.recent.borrow();
    let recent2 = input2.recent.borrow();
    let stable1 = input1.stable.borrow();
    let stable2 = input2.stable.borrow();

    // recent1 × stable2
    for batch in stable2.iter() {
        join_helper(&recent1, batch, |k, v1, v2| {
            results.push(logic(k, v1, v2));
        });
    }

    // stable1 × recent2
    for batch in stable1.iter() {
        join_helper(batch, &recent2, |k, v1, v2| {
            results.push(logic(k, v1, v2));
        });
    }

    drop(recent1);
    drop(recent2);
    drop(stable1);
    drop(stable2);

    output.insert(Relation::new(results));
}

// ============================================================
// Leaper trait and implementations for multi-way join
// ============================================================

pub trait Leaper<Tuple, Val> {
    /// Estimate the number of proposed extensions for this prefix.
    fn count(&mut self, prefix: &Tuple) -> usize;
    /// Return sorted proposed extensions.
    fn propose(&mut self, prefix: &Tuple) -> Vec<Val>;
    /// Retain only values that this leaper would also propose.
    fn intersect(&mut self, prefix: &Tuple, values: &mut Vec<Val>);
}

// ---- ExtendWith ----

/// Proposes extensions by looking up a key (extracted from the prefix)
/// in a sorted (Key, Val) relation.
pub struct ExtendWith<'a, Key: Ord, Val: Ord, Tuple, F: Fn(&Tuple) -> Key> {
    relation: &'a [(Key, Val)],
    key_func: F,
    _phantom: std::marker::PhantomData<Tuple>,
}

impl<'a, Key: Ord, Val: Ord, Tuple, F: Fn(&Tuple) -> Key>
    ExtendWith<'a, Key, Val, Tuple, F>
{
    pub fn new(relation: &'a [(Key, Val)], key_func: F) -> Self {
        ExtendWith {
            relation,
            key_func,
            _phantom: std::marker::PhantomData,
        }
    }

    fn find_vals(&self, key: &Key) -> &'a [(Key, Val)] {
        let start = gallop(self.relation, |x| &x.0 < key);
        let count = start.iter().take_while(|x| &x.0 == key).count();
        &start[..count]
    }
}

impl<'a, Key: Ord, Val: Ord + Clone, Tuple, F: Fn(&Tuple) -> Key>
    Leaper<Tuple, Val> for ExtendWith<'a, Key, Val, Tuple, F>
{
    fn count(&mut self, prefix: &Tuple) -> usize {
        let key = (self.key_func)(prefix);
        self.find_vals(&key).len()
    }

    fn propose(&mut self, prefix: &Tuple) -> Vec<Val> {
        let key = (self.key_func)(prefix);
        self.find_vals(&key).iter().map(|x| x.1.clone()).collect()
    }

    fn intersect(&mut self, prefix: &Tuple, values: &mut Vec<Val>) {
        let key = (self.key_func)(prefix);
        let range = self.find_vals(&key);
        let mut idx = 0;
        values.retain(|v| {
            while idx < range.len() && &range[idx].1 < v {
                idx += 1;
            }
            idx < range.len() && &range[idx].1 == v
        });
    }
}

// ---- ExtendAnti ----

/// Removes proposed values that are present in a relation (negative extension).
pub struct ExtendAnti<'a, Key: Ord, Val: Ord, Tuple, F: Fn(&Tuple) -> Key> {
    relation: &'a [(Key, Val)],
    key_func: F,
    _phantom: std::marker::PhantomData<Tuple>,
}

impl<'a, Key: Ord, Val: Ord, Tuple, F: Fn(&Tuple) -> Key>
    ExtendAnti<'a, Key, Val, Tuple, F>
{
    pub fn new(relation: &'a [(Key, Val)], key_func: F) -> Self {
        ExtendAnti {
            relation,
            key_func,
            _phantom: std::marker::PhantomData,
        }
    }

    fn find_vals(&self, key: &Key) -> &'a [(Key, Val)] {
        let start = gallop(self.relation, |x| &x.0 < key);
        let count = start.iter().take_while(|x| &x.0 == key).count();
        &start[..count]
    }
}

impl<'a, Key: Ord, Val: Ord + Clone, Tuple, F: Fn(&Tuple) -> Key>
    Leaper<Tuple, Val> for ExtendAnti<'a, Key, Val, Tuple, F>
{
    fn count(&mut self, _prefix: &Tuple) -> usize {
        usize::MAX // never the minimum proposer
    }

    fn propose(&mut self, _prefix: &Tuple) -> Vec<Val> {
        panic!("ExtendAnti should never propose");
    }

    fn intersect(&mut self, prefix: &Tuple, values: &mut Vec<Val>) {
        let key = (self.key_func)(prefix);
        let range = self.find_vals(&key);
        let mut idx = 0;
        values.retain(|v| {
            while idx < range.len() && &range[idx].1 < v {
                idx += 1;
            }
            // keep if NOT found
            !(idx < range.len() && &range[idx].1 == v)
        });
    }
}

// ---- FilterAnti ----

/// Blocks all extensions if a key (extracted from the prefix) exists in a
/// sorted set. Returns count=0 when found, usize::MAX otherwise.
pub struct FilterAnti<'a, Key: Ord, Val, Tuple, F: Fn(&Tuple) -> Key> {
    relation: &'a [Key],
    key_func: F,
    _phantom: std::marker::PhantomData<(Tuple, Val)>,
}

impl<'a, Key: Ord, Val, Tuple, F: Fn(&Tuple) -> Key>
    FilterAnti<'a, Key, Val, Tuple, F>
{
    pub fn new(relation: &'a [Key], key_func: F) -> Self {
        FilterAnti {
            relation,
            key_func,
            _phantom: std::marker::PhantomData,
        }
    }
}

impl<'a, Key: Ord, Val: Ord + Clone, Tuple, F: Fn(&Tuple) -> Key>
    Leaper<Tuple, Val> for FilterAnti<'a, Key, Val, Tuple, F>
{
    fn count(&mut self, prefix: &Tuple) -> usize {
        let key = (self.key_func)(prefix);
        if self.relation.binary_search(&key).is_ok() {
            usize::MAX
        } else {
            0
        }
    }

    fn propose(&mut self, _prefix: &Tuple) -> Vec<Val> {
        panic!("FilterAnti should never propose");
    }

    fn intersect(&mut self, _prefix: &Tuple, _values: &mut Vec<Val>) {
        // no-op: we only arrive here when count was usize::MAX
    }
}

// ============================================================
// Multi-way join
// ============================================================

/// Multi-way join using the Leaper protocol.
///
/// For each tuple in `source.recent`:
///   1. Ask every leaper for its count estimate.
///   2. Have the leaper with minimum count propose extensions.
///   3. Have all other leapers intersect (filter) the proposals.
///   4. Apply `logic` to each surviving (prefix, val) pair.
pub fn leapjoin_into<Tuple, Val, Result>(
    source: &Variable<Tuple>,
    leapers: &mut [&mut dyn Leaper<Tuple, Val>],
    output: &Variable<Result>,
    mut logic: impl FnMut(&Tuple, &Val) -> Result,
) where
    Tuple: Ord + Clone,
    Val: Ord + Clone,
    Result: Ord + Clone,
{
    let mut result = Vec::new();

    let recent = source.recent.borrow();
    for tuple in recent.elements.iter() {
        // 1. Find minimum-count leaper
        let mut min_index = 0;
        let mut min_count = usize::MAX;
        for (i, leaper) in leapers.iter_mut().enumerate() {
            let c = leaper.count(tuple);
            if c < min_count {
                min_count = c;
                min_index = i;
            }
        }

        // Skip if any leaper vetoes (count == 0)
        if min_count > 0 {
            // 2. Propose from minimum-count leaper
            let mut values = leapers[min_index].propose(tuple);

            // 3. Intersect with all others
            for (i, leaper) in leapers.iter_mut().enumerate() {
                if i != min_index {
                    leaper.intersect(tuple, &mut values);
                }
            }

            // 4. Emit results
            for val in values.iter() {
                result.push(logic(tuple, val));
            }
        }
    }
    drop(recent);

    output.insert(Relation::new(result));
}
