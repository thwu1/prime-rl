
#include <iostream>
#include <vector>
#include <algorithm>
#include <cstdint>
#include <utility>

using namespace std;

struct BitVector {
    vector<uint64_t> words;
    vector<int> cum;
    int n;

    BitVector() : n(0) {}

    void build(const vector<bool>& bits) {
        n = bits.size();
        int nw = (n + 63) / 64;
        words.assign(nw, 0);
        for (int i = 0; i < n; i++)
            if (bits[i]) words[i >> 6] |= 1ULL << (i & 63);
        cum.resize(nw + 1, 0);
        for (int i = 0; i < nw; i++)
            cum[i + 1] = cum[i] + __builtin_popcountll(words[i]);
    }

    bool get(int i) const { return (words[i >> 6] >> (i & 63)) & 1; }

    int rank1(int i) const {
        if (i <= 0) return 0;
        if (i > n) i = n;
        int w = i >> 6, b = i & 63;
        int r = cum[w];
        if (b > 0) r += __builtin_popcountll(words[w] & ((1ULL << b) - 1));
        return r;
    }

    int rank0(int i) const {
        if (i <= 0) return 0;
        if (i > n) i = n;
        return i - rank1(i);
    }
};

struct WaveletTree {
    vector<BitVector> bv;
    int n, sigma, levels;

    void build(const vector<int>& seq, int sigma_) {
        n = seq.size();
        sigma = sigma_;
        if (n == 0) { levels = 0; return; }
        levels = 0;
        for (int s = max(sigma - 1, 1); s > 0; s >>= 1) levels++;

        bv.resize(levels);
        vector<int> cur = seq;
        vector<pair<int, int>> nodes = {{0, n}};

        for (int l = 0; l < levels; l++) {
            int bit = levels - 1 - l;
            vector<bool> bits(n, false);
            vector<int> nxt(n);
            vector<pair<int, int>> nnodes;

            for (auto& [nlo, nhi] : nodes) {
                vector<int> left_elems, right_elems;
                for (int i = nlo; i < nhi; i++) {
                    if ((cur[i] >> bit) & 1) {
                        bits[i] = true;
                        right_elems.push_back(cur[i]);
                    } else {
                        left_elems.push_back(cur[i]);
                    }
                }
                int mid = nlo + (int)left_elems.size();
                for (int i = 0; i < (int)left_elems.size(); i++)
                    nxt[nlo + i] = left_elems[i];
                for (int i = 0; i < (int)right_elems.size(); i++)
                    nxt[mid + i] = right_elems[i];
                nnodes.push_back({nlo, mid});
                nnodes.push_back({mid, nhi});
            }
            bv[l].build(bits);
            cur = nxt;
            nodes = nnodes;
        }
    }

    int access(int i) const {
        if (n == 0 || i < 0 || i >= n) return -1;
        int pos = i, lo = 0, hi = n, c = 0;
        for (int l = 0; l < levels; l++) {
            int bit = levels - 1 - l;
            int zeros = bv[l].rank0(hi) - bv[l].rank0(lo);
            if (!bv[l].get(pos)) {
                pos = lo + bv[l].rank0(pos) - bv[l].rank0(lo);
                hi = lo + zeros;
            } else {
                c |= (1 << bit);
                pos = lo + zeros + bv[l].rank1(pos) - bv[l].rank1(lo);
                lo += zeros;
            }
        }
        return c;
    }

    int rank(int c, int i) const {
        if (n == 0 || i <= 0 || c < 0 || c >= sigma) return 0;
        if (i > n) i = n;
        int lo = 0, hi = n, pos = i;
        for (int l = 0; l < levels; l++) {
            int bit = levels - 1 - l;
            int zeros = bv[l].rank0(hi) - bv[l].rank0(lo);
            if (!((c >> bit) & 1)) {
                pos = lo + bv[l].rank0(pos) - bv[l].rank0(lo);
                hi = lo + zeros;
            } else {
                pos = lo + zeros + bv[l].rank1(pos) - bv[l].rank1(lo);
                lo += zeros;
            }
        }
        return pos - lo;
    }

    int select(int c, int j) const {
        if (n == 0 || j <= 0 || c < 0 || c >= sigma) return -1;
        if (rank(c, n) < j) return -1;
        int lo_s = 0, hi_s = n - 1;
        while (lo_s < hi_s) {
            int mid = lo_s + (hi_s - lo_s) / 2;
            if (rank(c, mid + 1) < j) lo_s = mid + 1;
            else hi_s = mid;
        }
        return lo_s;
    }

    int kth(int ql, int qr, int k) const {
        if (n == 0 || ql < 0 || qr > n || ql >= qr || k <= 0 || k > qr - ql)
            return -1;
        int lo = 0, hi = n, c = 0;
        for (int l = 0; l < levels; l++) {
            int bit = levels - 1 - l;
            int zeros_node = bv[l].rank0(hi) - bv[l].rank0(lo);
            int zeros_query = bv[l].rank0(qr) - bv[l].rank0(ql);
            if (k <= zeros_query) {
                ql = lo + bv[l].rank0(ql) - bv[l].rank0(lo);
                qr = lo + bv[l].rank0(qr) - bv[l].rank0(lo);
                hi = lo + zeros_node;
            } else {
                k -= zeros_query;
                c |= (1 << bit);
                ql = lo + zeros_node + bv[l].rank1(ql) - bv[l].rank1(lo);
                qr = lo + zeros_node + bv[l].rank1(qr) - bv[l].rank1(lo);
                lo += zeros_node;
            }
        }
        return c;
    }

    int count_less(int pos, int val) const {
        if (n == 0 || pos <= 0) return 0;
        if (pos > n) pos = n;
        if (val <= 0) return 0;
        if (val >= (1 << levels)) return pos;
        int lo = 0, hi = n, p = pos, result = 0;
        for (int l = 0; l < levels; l++) {
            int bit = levels - 1 - l;
            int zeros_node = bv[l].rank0(hi) - bv[l].rank0(lo);
            int zeros_query = bv[l].rank0(p) - bv[l].rank0(lo);
            if ((val >> bit) & 1) {
                result += zeros_query;
                p = lo + zeros_node + bv[l].rank1(p) - bv[l].rank1(lo);
                lo += zeros_node;
            } else {
                p = lo + bv[l].rank0(p) - bv[l].rank0(lo);
                hi = lo + zeros_node;
            }
        }
        return result;
    }

    int range_count(int ql, int qr, int lo_val, int hi_val) const {
        if (n == 0 || ql >= qr || ql < 0 || qr > n || lo_val >= hi_val) return 0;
        return (count_less(qr, hi_val) - count_less(ql, hi_val))
             - (count_less(qr, lo_val) - count_less(ql, lo_val));
    }

    int _range_next(int ql, int qr, int c, int lo, int hi,
                    int level, int val_lo, int val_hi) const {
        if (ql >= qr) return -1;
        if (level == levels) {
            return (val_lo >= c && val_lo < sigma) ? val_lo : -1;
        }
        int bit = levels - 1 - level;
        int zeros = bv[level].rank0(hi) - bv[level].rank0(lo);

        int left_ql = lo + bv[level].rank0(ql) - bv[level].rank0(lo);
        int left_qr = lo + bv[level].rank0(qr) - bv[level].rank0(lo);
        int right_ql = lo + zeros + bv[level].rank1(ql) - bv[level].rank1(lo);
        int right_qr = lo + zeros + bv[level].rank1(qr) - bv[level].rank1(lo);

        int val_mid = val_lo + (1 << bit);

        if (c < val_mid) {
            int res = _range_next(left_ql, left_qr, c, lo, lo + zeros,
                                  level + 1, val_lo, val_mid);
            if (res != -1) return res;
            return _range_next(right_ql, right_qr, c, lo + zeros, hi,
                               level + 1, val_mid, val_hi);
        } else {
            return _range_next(right_ql, right_qr, c, lo + zeros, hi,
                               level + 1, val_mid, val_hi);
        }
    }

    int range_next(int ql, int qr, int c) const {
        if (n == 0 || ql < 0 || qr > n || ql >= qr) return -1;
        return _range_next(ql, qr, c, 0, n, 0, 0, 1 << levels);
    }

    int _range_prev(int ql, int qr, int c, int lo, int hi,
                    int level, int val_lo, int val_hi) const {
        if (ql >= qr) return -1;
        if (level == levels) {
            return (val_lo <= c && val_lo < sigma) ? val_lo : -1;
        }
        int bit = levels - 1 - level;
        int zeros = bv[level].rank0(hi) - bv[level].rank0(lo);

        int left_ql = lo + bv[level].rank0(ql) - bv[level].rank0(lo);
        int left_qr = lo + bv[level].rank0(qr) - bv[level].rank0(lo);
        int right_ql = lo + zeros + bv[level].rank1(ql) - bv[level].rank1(lo);
        int right_qr = lo + zeros + bv[level].rank1(qr) - bv[level].rank1(lo);

        int val_mid = val_lo + (1 << bit);

        if (c >= val_mid) {
            int res = _range_prev(right_ql, right_qr, c, lo + zeros, hi,
                                  level + 1, val_mid, val_hi);
            if (res != -1) return res;
            return _range_prev(left_ql, left_qr, c, lo, lo + zeros,
                               level + 1, val_lo, val_mid);
        } else {
            return _range_prev(left_ql, left_qr, c, lo, lo + zeros,
                               level + 1, val_lo, val_mid);
        }
    }

    int range_prev(int ql, int qr, int c) const {
        if (n == 0 || ql < 0 || qr > n || ql >= qr) return -1;
        return _range_prev(ql, qr, c, 0, n, 0, 0, 1 << levels);
    }
};

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);

    int n, sigma;
    cin >> n >> sigma;

    vector<int> seq(n);
    for (int i = 0; i < n; i++) cin >> seq[i];

    WaveletTree wt;
    wt.build(seq, sigma);

    int q;
    cin >> q;

    while (q--) {
        char type;
        cin >> type;
        if (type == 'A') {
            int i; cin >> i;
            cout << wt.access(i) << '\n';
        } else if (type == 'R') {
            int c, i; cin >> c >> i;
            cout << wt.rank(c, i) << '\n';
        } else if (type == 'S') {
            int c, j; cin >> c >> j;
            cout << wt.select(c, j) << '\n';
        } else if (type == 'K') {
            int l, r, k; cin >> l >> r >> k;
            cout << wt.kth(l, r, k) << '\n';
        } else if (type == 'C') {
            int l, r, lo, hi; cin >> l >> r >> lo >> hi;
            cout << wt.range_count(l, r, lo, hi) << '\n';
        } else if (type == 'V') {
            int l, r, c; cin >> l >> r >> c;
            cout << wt.range_next(l, r, c) << '\n';
        } else if (type == 'P') {
            int l, r, c; cin >> l >> r >> c;
            cout << wt.range_prev(l, r, c) << '\n';
        }
    }

    return 0;
}
