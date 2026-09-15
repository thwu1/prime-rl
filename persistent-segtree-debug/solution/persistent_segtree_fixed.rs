/// Persistent Segment Tree with Affine Lazy Propagation (CORRECT)
///
/// Supports versioned range-transform updates (A[i] = a*A[i] + b mod P)
/// and range-sum queries under modular arithmetic. Each update creates
/// a new version via path-copying.

pub struct PersistentSegTree {
    modp: u64,
    sum: Vec<u64>,
    lazy_mul: Vec<u64>,
    lazy_add: Vec<u64>,
    lc: Vec<usize>,
    rc: Vec<usize>,
    pub roots: Vec<usize>,
}

impl PersistentSegTree {
    pub fn new(modp: u64) -> Self {
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

    /// FIX 1: Copy lazy_mul and lazy_add from source to preserve
    /// deferred transforms across version forks.
    fn copy_of(&mut self, src: usize) -> usize {
        let id = self.sum.len();
        self.sum.push(self.sum[src]);
        self.lazy_mul.push(self.lazy_mul[src]);
        self.lazy_add.push(self.lazy_add[src]);
        self.lc.push(self.lc[src]);
        self.rc.push(self.rc[src]);
        id
    }

    /// Apply an affine transform (mul, add) to node v covering `size` elements.
    /// Updates both the aggregate sum and composes with existing lazy.
    /// Composition law: applying (m2, a2) after existing (m1, a1) gives
    /// (m2*m1, m2*a1 + a2) because x -> m1*x + a1 -> m2*(m1*x+a1) + a2.
    fn apply_lazy(&mut self, v: usize, size: u64, mul: u64, add: u64) {
        let p = self.modp;
        self.sum[v] = (mul % p * (self.sum[v] % p) % p + add % p * (size % p) % p) % p;
        self.lazy_mul[v] = mul % p * (self.lazy_mul[v] % p) % p;
        self.lazy_add[v] = (mul % p * (self.lazy_add[v] % p) % p + add % p) % p;
    }

    /// FIX 2: Push full affine transform to both children with correct
    /// per-child range sizes and proper semigroup composition.
    fn push(&mut self, v: usize, lo: usize, hi: usize) {
        if self.lazy_mul[v] != 1 || self.lazy_add[v] != 0 {
            let mid = lo + (hi - lo) / 2;
            let mul = self.lazy_mul[v];
            let add = self.lazy_add[v];

            let nl = self.copy_of(self.lc[v]);
            let nr = self.copy_of(self.rc[v]);
            self.lc[v] = nl;
            self.rc[v] = nr;

            let left_size = (mid - lo + 1) as u64;
            let right_size = (hi - mid) as u64;

            self.apply_lazy(nl, left_size, mul, add);
            self.apply_lazy(nr, right_size, mul, add);

            self.lazy_mul[v] = 1;
            self.lazy_add[v] = 0;
        }
    }

    /// FIX 3: Implement persistent range affine update via path-copying.
    pub fn update_affine(
        &mut self,
        prev: usize,
        lo: usize,
        hi: usize,
        ql: usize,
        qr: usize,
        a: u64,
        b: u64,
    ) -> usize {
        let v = self.copy_of(prev);
        if ql <= lo && hi <= qr {
            let size = (hi - lo + 1) as u64;
            self.apply_lazy(v, size, a, b);
            return v;
        }
        self.push(v, lo, hi);
        let mid = lo + (hi - lo) / 2;
        if ql <= mid {
            let nl = self.update_affine(self.lc[v], lo, mid, ql, qr, a, b);
            self.lc[v] = nl;
        }
        if qr > mid {
            let nr = self.update_affine(self.rc[v], mid + 1, hi, ql, qr, a, b);
            self.rc[v] = nr;
        }
        self.pull(v);
        v
    }

    /// FIX 4: Implement range sum query with correct lazy push-down.
    pub fn query_sum(
        &mut self,
        v: usize,
        lo: usize,
        hi: usize,
        ql: usize,
        qr: usize,
    ) -> u64 {
        if v == 0 {
            return 0;
        }
        if ql <= lo && hi <= qr {
            return self.sum[v];
        }
        self.push(v, lo, hi);
        let mid = lo + (hi - lo) / 2;
        let mut res = 0u64;
        if ql <= mid {
            res = (res + self.query_sum(self.lc[v], lo, mid, ql, qr)) % self.modp;
        }
        if qr > mid {
            res = (res + self.query_sum(self.rc[v], mid + 1, hi, ql, qr)) % self.modp;
        }
        res
    }
}
