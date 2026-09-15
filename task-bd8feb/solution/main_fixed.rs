use std::io::{self, Read, Write, BufWriter};

/// Complete Link-Cut Tree implementation for dynamic forest queries.
/// Supports link, cut, path_sum, path_max, path_min, path add, and point update.
struct LinkCutTree {
    ch: Vec<[usize; 2]>,
    fa: Vec<usize>,
    val: Vec<i64>,
    sum: Vec<i64>,
    mx: Vec<i64>,
    mn: Vec<i64>,
    sz: Vec<usize>,
    add_tag: Vec<i64>,
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
            mx: vec![i64::MIN; cap],
            mn: vec![i64::MAX; cap],
            sz: vec![0; cap],
            add_tag: vec![0; cap],
            rev: vec![false; cap],
        }
    }

    fn init(&mut self, x: usize, v: i64) {
        self.val[x] = v;
        self.sum[x] = v;
        self.mx[x] = v;
        self.mn[x] = v;
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
        self.mx[x] = self.val[x];
        self.mn[x] = self.val[x];
        if l != 0 {
            self.mx[x] = self.mx[x].max(self.mx[l]);
            self.mn[x] = self.mn[x].min(self.mn[l]);
        }
        if r != 0 {
            self.mx[x] = self.mx[x].max(self.mx[r]);
            self.mn[x] = self.mn[x].min(self.mn[r]);
        }
    }

    fn tag_add(&mut self, x: usize, d: i64) {
        if x == 0 {
            return;
        }
        self.val[x] += d;
        self.sum[x] += d * self.sz[x] as i64;
        self.mx[x] += d;
        self.mn[x] += d;
        self.add_tag[x] += d;
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
        if self.add_tag[x] != 0 {
            let d = self.add_tag[x];
            self.tag_add(self.ch[x][0], d);
            self.tag_add(self.ch[x][1], d);
            self.add_tag[x] = 0;
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
        self.fa[x] = 0;
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

    fn query_max(&mut self, x: usize, y: usize) -> i64 {
        self.split(x, y);
        self.mx[y]
    }

    fn query_min(&mut self, x: usize, y: usize) -> i64 {
        self.split(x, y);
        self.mn[y]
    }

    fn path_add(&mut self, x: usize, y: usize, d: i64) {
        self.split(x, y);
        self.tag_add(y, d);
    }

    fn update_val(&mut self, x: usize, w: i64) {
        self.access(x);
        self.val[x] = w;
        self.push_up(x);
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

    let _q: usize = lines.next().unwrap().trim().parse().unwrap();

    // Consume the command stream to EOF.  Some real inputs contain a stale
    // operation count, and silently dropping valid trailing operations makes
    // an otherwise-correct dynamic forest return an incomplete transcript.
    for line in lines {
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
            "path_max" => {
                let u: usize = tok[1].parse().unwrap();
                let v: usize = tok[2].parse().unwrap();
                writeln!(out, "{}", lct.query_max(u, v)).unwrap();
            }
            "path_min" => {
                let u: usize = tok[1].parse().unwrap();
                let v: usize = tok[2].parse().unwrap();
                writeln!(out, "{}", lct.query_min(u, v)).unwrap();
            }
            "add" => {
                let u: usize = tok[1].parse().unwrap();
                let v: usize = tok[2].parse().unwrap();
                let d: i64 = tok[3].parse().unwrap();
                lct.path_add(u, v, d);
            }
            "update" => {
                let u: usize = tok[1].parse().unwrap();
                let w: i64 = tok[2].parse().unwrap();
                lct.update_val(u, w);
            }
            _ => {}
        }
    }
}
