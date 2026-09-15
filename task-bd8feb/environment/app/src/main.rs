use std::io::{self, Read, Write, BufWriter};

/// Link-Cut Tree implementation for dynamic forest queries.
/// Currently supports link, cut, and path_sum.
/// The remaining operations described in problem.md (path_max, path_min,
/// add, update) are not yet implemented.
struct LinkCutTree {
    ch: Vec<[usize; 2]>,
    fa: Vec<usize>,
    val: Vec<i64>,
    sum: Vec<i64>,
    sz: Vec<usize>,
    rev: Vec<bool>,
}

impl LinkCutTree {
    fn new(n: usize) -> Self {
        let cap = n + 1;
        LinkCutTree {
            ch: vec![[0, 0]; cap],
            fa: vec![0; cap],
            val: vec![0; cap],
            sum: vec![0; cap],
            sz: vec![0; cap],
            rev: vec![false; cap],
        }
    }

    fn init(&mut self, x: usize, v: i64) {
        self.val[x] = v;
        self.sum[x] = v;
        self.sz[x] = 1;
    }

    #[inline]
    fn is_root(&self, x: usize) -> bool {
        let f = self.fa[x];
        f == 0 || (self.ch[f][0] != x && self.ch[f][1] != x)
    }

    fn push_up(&mut self, x: usize) {
        if x == 0 {
            return;
        }
        let (l, r) = (self.ch[x][0], self.ch[x][1]);
        self.sz[x] = self.sz[l] + 1 + self.sz[r];
        self.sum[x] = self.sum[l] + self.val[x] + self.sum[r];
    }

    fn tag_rev(&mut self, x: usize) {
        if x == 0 {
            return;
        }
        self.ch[x].swap(0, 1);
        self.rev[x] ^= true;
    }

    fn push_down(&mut self, x: usize) {
        if self.rev[x] {
            self.tag_rev(self.ch[x][0]);
            self.tag_rev(self.ch[x][1]);
            self.rev[x] = false;
        }
    }

    #[inline]
    fn dir(&self, x: usize) -> usize {
        if self.ch[self.fa[x]][1] == x {
            1
        } else {
            0
        }
    }

    fn rotate(&mut self, x: usize) {
        let y = self.fa[x];
        let z = self.fa[y];
        let k = self.dir(x);
        let w = self.ch[x][1 - k];
        if !self.is_root(y) {
            let dy = self.dir(y);
            self.ch[z][dy] = x;
        }
        self.ch[x][1 - k] = y;
        self.ch[y][k] = w;
        if w != 0 {
            self.fa[w] = y;
        }
        self.fa[y] = x;
        self.fa[x] = z;
        self.push_up(y);
        self.push_up(x);
    }

    fn splay(&mut self, x: usize) {
        let mut path = vec![x];
        let mut u = x;
        while !self.is_root(u) {
            u = self.fa[u];
            path.push(u);
        }
        for &u in path.iter().rev() {
            self.push_down(u);
        }
        while !self.is_root(x) {
            let y = self.fa[x];
            if !self.is_root(y) {
                if self.dir(x) == self.dir(y) {
                    self.rotate(y);
                } else {
                    self.rotate(x);
                }
            }
            self.rotate(x);
        }
        self.push_up(x);
    }

    fn access(&mut self, x: usize) {
        let mut last = 0usize;
        let mut u = x;
        while u != 0 {
            self.splay(u);
            self.ch[u][1] = last;
            self.push_up(u);
            last = u;
            u = self.fa[u];
        }
        self.splay(x);
    }

    fn make_root(&mut self, x: usize) {
        self.access(x);
        self.tag_rev(x);
    }

    fn link(&mut self, x: usize, y: usize) {
        self.make_root(x);
        self.fa[x] = y;
    }

    fn cut(&mut self, x: usize, y: usize) {
        self.make_root(x);
        self.access(y);
        self.ch[y][0] = 0;
        self.push_up(y);
    }

    fn split(&mut self, x: usize, y: usize) {
        self.make_root(x);
        self.access(y);
    }

    fn query_sum(&mut self, x: usize, y: usize) -> i64 {
        self.split(x, y);
        self.sum[y]
    }
}

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());

    let mut lines = input.lines();

    let n: usize = lines.next().unwrap().trim().parse().unwrap();
    let weights: Vec<i64> = lines
        .next()
        .unwrap()
        .trim()
        .split_whitespace()
        .map(|s| s.parse().unwrap())
        .collect();

    let mut lct = LinkCutTree::new(n);
    for i in 1..=n {
        lct.init(i, weights[i - 1]);
    }

    let q: usize = lines.next().unwrap().trim().parse().unwrap();

    for _ in 0..q {
        let line = lines.next().unwrap();
        let tok: Vec<&str> = line.trim().split_whitespace().collect();
        match tok[0] {
            "link" => {
                let u: usize = tok[1].parse().unwrap();
                let v: usize = tok[2].parse().unwrap();
                lct.link(u, v);
            }
            "cut" => {
                let u: usize = tok[1].parse().unwrap();
                let v: usize = tok[2].parse().unwrap();
                lct.cut(u, v);
            }
            "path_sum" => {
                let u: usize = tok[1].parse().unwrap();
                let v: usize = tok[2].parse().unwrap();
                writeln!(out, "{}", lct.query_sum(u, v)).unwrap();
            }
            _ => {
                // Other operations not yet implemented
            }
        }
    }
}
