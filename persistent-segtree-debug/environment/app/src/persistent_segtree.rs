/// Persistent Segment Tree with Lazy Propagation
///
/// Must support versioned range-transform updates and range-sum queries
/// under modular arithmetic. Each update creates a new version via
/// path-copying; queries can target any previously created version.
///
/// The lazy propagation must handle composable pending operations
/// that are distributed to children during push-down and correctly
/// preserved across version forks via path-copying.

pub struct PersistentSegTree {
    modp: u64,
    sum: Vec<u64>,
    /// Multiplicative component of the pending lazy transform
    lazy_mul: Vec<u64>,
    /// Additive component of the pending lazy transform
    lazy_add: Vec<u64>,
    lc: Vec<usize>,
    rc: Vec<usize>,
    pub roots: Vec<usize>,
}

impl PersistentSegTree {
    pub fn new(modp: u64) -> Self {
        // Index 0 is the null sentinel node
        PersistentSegTree {
            modp,
            sum: vec![0],
            lazy_mul: vec![1],
            lazy_add: vec![0],
            lc: vec![0],
            rc: vec![0],
            roots: Vec::new(),
        }
    }

    fn alloc(&mut self) -> usize {
        let id = self.sum.len();
        self.sum.push(0);
        self.lazy_mul.push(1);
        self.lazy_add.push(0);
        self.lc.push(0);
        self.rc.push(0);
        id
    }

    fn pull(&mut self, v: usize) {
        let l = self.lc[v];
        let r = self.rc[v];
        self.sum[v] = (self.sum[l] + self.sum[r]) % self.modp;
    }

    /// Build the initial segment tree from array `a` (1-indexed: lo..=hi).
    pub fn build(&mut self, a: &[u64], lo: usize, hi: usize) -> usize {
        let v = self.alloc();
        if lo == hi {
            self.sum[v] = a[lo - 1] % self.modp;
            return v;
        }
        let mid = lo + (hi - lo) / 2;
        let left = self.build(a, lo, mid);
        let right = self.build(a, mid + 1, hi);
        self.lc[v] = left;
        self.rc[v] = right;
        self.pull(v);
        v
    }

    /// Create a copy of node `src` for path-copying persistence.
    /// The copy must correctly carry over all state needed for
    /// deferred lazy operations to work across version forks.
    fn copy_of(&mut self, src: usize) -> usize {
        let id = self.sum.len();
        self.sum.push(self.sum[src]);
        self.lazy_mul.push(1);   // reset to identity
        self.lazy_add.push(0);   // reset to identity
        self.lc.push(self.lc[src]);
        self.rc.push(self.rc[src]);
        id
    }

    /// Push pending lazy transform down to children, cloning them
    /// for persistence. Must correctly compose the parent's pending
    /// transform with each child's existing lazy state, and update
    /// each child's aggregate (sum) to reflect the applied transform.
    fn push(&mut self, v: usize, lo: usize, hi: usize) {
        if self.lazy_mul[v] != 1 || self.lazy_add[v] != 0 {
            let _mid = lo + (hi - lo) / 2;
            let add = self.lazy_add[v];

            let nl = self.copy_of(self.lc[v]);
            let nr = self.copy_of(self.rc[v]);
            self.lc[v] = nl;
            self.rc[v] = nr;

            let half = ((hi - lo + 1) / 2) as u64;

            self.sum[nl] = (self.sum[nl] + add * half) % self.modp;
            self.lazy_add[nl] = (self.lazy_add[nl] + add) % self.modp;

            self.sum[nr] = (self.sum[nr] + add * half) % self.modp;
            self.lazy_add[nr] = (self.lazy_add[nr] + add) % self.modp;

            self.lazy_mul[v] = 1;
            self.lazy_add[v] = 0;
        }
    }

    /// Range transform: for every element in [ql, qr] of the version
    /// rooted at `prev`, apply A[i] = (a * A[i] + b) mod P.
    /// Returns the root index of the new version.
    pub fn update_affine(
        &mut self,
        prev: usize,
        _lo: usize,
        _hi: usize,
        _ql: usize,
        _qr: usize,
        _a: u64,
        _b: u64,
    ) -> usize {
        // TODO: implement persistent range transform
        prev
    }

    /// Query the sum of elements in [ql, qr] mod P for the version
    /// rooted at `v`.
    pub fn query_sum(
        &mut self,
        _v: usize,
        _lo: usize,
        _hi: usize,
        _ql: usize,
        _qr: usize,
    ) -> u64 {
        // TODO: implement range sum query with lazy handling
        0
    }
}
