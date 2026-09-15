
#include <iostream>
#include <vector>
#include "wavelet_tree.hpp"

using namespace std;

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
