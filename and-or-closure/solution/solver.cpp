/*
 * AND-OR Closure Size — efficient C++ solver.
 *
 *
 * Algorithm:
 *   1. Remove constant bits (always 0 or always 1 across all values).
 *   2. Group remaining active bits into equivalence classes (same 0/1 column).
 *   3. Pick one representative per class; build a DAG where edge i->j means
 *      "in every input value where rep-bit i is set, rep-bit j is also set."
 *   4. Count order ideals (downward-closed sets) of this DAG.
 *      - For R <= 22: brute-force enumerate all 2^R subsets.
 *      - For R > 22: meet-in-the-middle with antichain DP on each half.
 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include <set>
#include <map>
#include <algorithm>

using namespace std;
typedef unsigned long long u64;

long long count_brute(int R, const vector<int>& implies) {
    long long count = 0;
    for (int s = 0; s < (1 << R); s++) {
        bool ok = true;
        for (int i = 0; i < R; i++) {
            if ((s >> i) & 1) {
                if ((implies[i] & s) != implies[i]) {
                    ok = false;
                    break;
                }
            }
        }
        if (ok) count++;
    }
    return count;
}

long long count_mitm(int R, const vector<int>& implies) {
    int h = R / 2;
    int sh = R - h;
    int h_mask = (1 << h) - 1;
    int sh_mask = (1 << sh) - 1;

    vector<int> implies_fh(h), implies_sh(sh);
    for (int i = 0; i < h; i++)
        implies_fh[i] = implies[i] & h_mask;
    for (int j = 0; j < sh; j++)
        implies_sh[j] = (implies[h + j] >> h) & sh_mask;

    vector<int> req_fh(sh), force_sh(h);
    vector<int> up_sh(h, 0);
    for (int j = 0; j < sh; j++)
        req_fh[j] = implies[h + j] & h_mask;
    for (int i = 0; i < h; i++)
        force_sh[i] = (implies[i] >> h) & sh_mask;
    for (int j = 0; j < sh; j++)
        for (int i = 0; i < h; i++)
            if ((req_fh[j] >> i) & 1)
                up_sh[i] |= 1 << j;

    vector<int> comp_sh_v(sh, 0);
    for (int j = 0; j < sh; j++) {
        comp_sh_v[j] = 1 << j;
        for (int k = 0; k < sh; k++) {
            if (k == j) continue;
            if ((implies_sh[j] >> k) & 1) comp_sh_v[j] |= 1 << k;
            if ((implies_sh[k] >> j) & 1) comp_sh_v[j] |= 1 << k;
        }
    }

    vector<long long> ac(1 << sh, 0);
    ac[0] = 1;
    for (int m = 1; m < (1 << sh); m++) {
        int j = 31 - __builtin_clz(m);
        int without_j = m & ~(1 << j);
        int without_comp = without_j & ~comp_sh_v[j];
        ac[m] = ac[without_j] + ac[without_comp];
    }

    vector<int> comp_fh_v(h, 0);
    for (int i = 0; i < h; i++) {
        comp_fh_v[i] = 1 << i;
        for (int k = 0; k < h; k++) {
            if (k == i) continue;
            if ((implies_fh[i] >> k) & 1) comp_fh_v[i] |= 1 << k;
            if ((implies_fh[k] >> i) & 1) comp_fh_v[i] |= 1 << k;
        }
    }

    long long total = 0;
    struct Frame { int idx, ac_mask, down_bl, up_bl; };
    vector<Frame> stk;
    stk.push_back({0, 0, 0, 0});

    while (!stk.empty()) {
        Frame f = stk.back();
        stk.pop_back();
        if (f.idx == h) {
            int blocked = f.down_bl | f.up_bl;
            int free = sh_mask & ~blocked;
            total += ac[free];
            continue;
        }
        stk.push_back({f.idx + 1, f.ac_mask, f.down_bl, f.up_bl});
        if ((comp_fh_v[f.idx] & f.ac_mask) == 0) {
            stk.push_back({
                f.idx + 1,
                f.ac_mask | (1 << f.idx),
                f.down_bl | force_sh[f.idx],
                f.up_bl | up_sh[f.idx]
            });
        }
    }
    return total;
}

long long solve_case() {
    int n;
    scanf("%d", &n);

    vector<u64> values(n);
    for (int i = 0; i < n; i++)
        scanf("%llu", &values[i]);

    sort(values.begin(), values.end());
    values.erase(unique(values.begin(), values.end()), values.end());
    n = (int)values.size();

    if (n <= 1) return n;

    u64 all_and = values[0], all_or = values[0];
    for (int i = 1; i < n; i++) {
        all_and &= values[i];
        all_or |= values[i];
    }

    u64 active_mask = all_and ^ all_or;
    if (active_mask == 0) return 1;

    vector<int> active_bits;
    for (int b = 0; b < 41; b++)
        if ((active_mask >> b) & 1)
            active_bits.push_back(b);
    int num_active = (int)active_bits.size();

    set<u64> pset;
    for (auto v : values) {
        u64 p = 0;
        for (int i = 0; i < num_active; i++)
            if ((v >> active_bits[i]) & 1)
                p |= 1ULL << i;
        pset.insert(p);
    }
    vector<u64> unique_patterns(pset.begin(), pset.end());
    sort(unique_patterns.begin(), unique_patterns.end());

    map<vector<int>, int> col_to_rep;
    for (int i = 0; i < num_active; i++) {
        vector<int> col(unique_patterns.size());
        for (size_t j = 0; j < unique_patterns.size(); j++)
            col[j] = (unique_patterns[j] >> i) & 1;
        if (col_to_rep.find(col) == col_to_rep.end())
            col_to_rep[col] = i;
    }

    vector<int> representatives;
    for (auto& kv : col_to_rep)
        representatives.push_back(kv.second);
    sort(representatives.begin(), representatives.end());
    int R = (int)representatives.size();

    vector<int> implies_v(R, 0);
    for (int ri = 0; ri < R; ri++) {
        int bi = representatives[ri];
        u64 mask = (1ULL << num_active) - 1;
        for (auto p : unique_patterns)
            if ((p >> bi) & 1)
                mask &= p;
        int imp = 0;
        for (int rj = 0; rj < R; rj++) {
            int bj = representatives[rj];
            if ((mask >> bj) & 1)
                imp |= 1 << rj;
        }
        implies_v[ri] = imp;
    }

    if (R <= 22)
        return count_brute(R, implies_v);
    else
        return count_mitm(R, implies_v);
}

int main() {
    int T;
    scanf("%d", &T);
    for (int t = 0; t < T; t++)
        printf("%lld\n", solve_case());
    return 0;
}
