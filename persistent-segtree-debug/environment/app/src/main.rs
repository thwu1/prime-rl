use std::io::{self, Read, Write, BufWriter};

mod persistent_segtree;
use persistent_segtree::PersistentSegTree;

const MOD: u64 = 998244353;

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());

    let mut iter = input.split_whitespace();
    let n: usize = iter.next().unwrap().parse().unwrap();
    let q: usize = iter.next().unwrap().parse().unwrap();

    let a: Vec<u64> = (0..n)
        .map(|_| iter.next().unwrap().parse::<u64>().unwrap())
        .collect();

    let mut tree = PersistentSegTree::new(MOD);
    let root = tree.build(&a, 1, n);
    tree.roots.push(root); // version 0

    for _ in 0..q {
        let op: usize = iter.next().unwrap().parse().unwrap();
        match op {
            1 => {
                let v: usize = iter.next().unwrap().parse().unwrap();
                let l: usize = iter.next().unwrap().parse().unwrap();
                let r: usize = iter.next().unwrap().parse().unwrap();
                let a_val: u64 = iter.next().unwrap().parse().unwrap();
                let b_val: u64 = iter.next().unwrap().parse().unwrap();
                let new_root = tree.update_affine(tree.roots[v], 1, n, l, r, a_val, b_val);
                tree.roots.push(new_root);
            }
            2 => {
                let v: usize = iter.next().unwrap().parse().unwrap();
                let l: usize = iter.next().unwrap().parse().unwrap();
                let r: usize = iter.next().unwrap().parse().unwrap();
                let ans = tree.query_sum(tree.roots[v], 1, n, l, r);
                writeln!(out, "{}", ans).unwrap();
            }
            _ => unreachable!(),
        }
    }
}
