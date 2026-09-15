
#pragma once
#include "bitvector.hpp"
#include <algorithm>
#include <utility>

struct WaveletTree {
    std::vector<BitVector> bv;
    int n, sigma, levels;

    void build(const std::vector<int>& seq, int sigma_) {
        n = seq.size();
        sigma = sigma_;
        if (n == 0) { levels = 0; return; }
        levels = 0;
        for (int s = sigma; s > 1; s >>= 1) levels++;

        bv.resize(levels);
        std::vector<int> cur = seq;
        std::vector<std::pair<int, int>> nodes = {{0, n}};

        for (int l = 0; l < levels; l++) {
            int bit = levels - 1 - l;
            std::vector<bool> bits(n, false);
            std::vector<int> nxt(n);
            std::vector<std::pair<int, int>> nnodes;

            for (auto& [nlo, nhi] : nodes) {
                std::vector<int> left_elems, right_elems;
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
                hi = lo + zeros;
                pos = lo + bv[l].rank0(pos) - bv[l].rank0(lo);
            } else {
                lo += zeros;
                pos = lo + bv[l].rank1(pos) - bv[l].rank1(lo);
            }
        }
        return pos - lo;
    }

    int select(int c, int j) const {
        // TODO: implement
        return -1;
    }

    int kth(int ql, int qr, int k) const {
        // TODO: implement
        return -1;
    }

    int range_count(int ql, int qr, int lo_val, int hi_val) const {
        // TODO: implement
        return 0;
    }

    int range_next(int ql, int qr, int c) const {
        // TODO: implement
        return -1;
    }

    int range_prev(int ql, int qr, int c) const {
        // TODO: implement
        return -1;
    }
};
