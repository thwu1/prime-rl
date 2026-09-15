
#pragma once
#include <vector>
#include <cstdint>

struct BitVector {
    std::vector<uint64_t> words;
    std::vector<int> cum;
    int n;

    BitVector() : n(0) {}

    void build(const std::vector<bool>& bits) {
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
