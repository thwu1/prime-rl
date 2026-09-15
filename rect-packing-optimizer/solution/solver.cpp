/*
 *
 * Rectangle Ad Placement Solver
 * Algorithm: recursive area-proportional partition + simulated annealing + greedy expansion
 */
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <numeric>
#include <random>
#include <vector>

using namespace std;

static int N;
static vector<int> X, Y, R;
static vector<array<int,4>> rects; // {a, b, c, d}

static inline double sat_value(int r, int s) {
    double ratio = (double)min(r, s) / (double)max(r, s);
    return 1.0 - (1.0 - ratio) * (1.0 - ratio);
}

static inline double satisfaction(int i) {
    auto& rc = rects[i];
    if (rc[0] <= X[i] && rc[2] >= X[i] + 1 && rc[1] <= Y[i] && rc[3] >= Y[i] + 1) {
        int s = (rc[2] - rc[0]) * (rc[3] - rc[1]);
        return sat_value(R[i], s);
    }
    return 0.0;
}

// ---- Phase 1: Recursive area-proportional partition ----

static void do_partition(vector<int>& indices, int x1, int y1, int x2, int y2) {
    int k = (int)indices.size();
    if (k == 0) return;
    if (k == 1) {
        rects[indices[0]] = {x1, y1, x2, y2};
        return;
    }

    long long totalR = 0;
    for (int idx : indices) totalR += R[idx];

    double bestCost = 1e18;
    bool bestUseX = true;
    int bestSplitK = -1, bestSplitS = -1;
    vector<int> bestSorted;

    for (int useX = 0; useX < 2; useX++) {
        vector<int> sorted_idx = indices;
        if (useX) {
            sort(sorted_idx.begin(), sorted_idx.end(), [](int a, int b) {
                if (X[a] != X[b]) return X[a] < X[b];
                return Y[a] < Y[b];
            });
        } else {
            sort(sorted_idx.begin(), sorted_idx.end(), [](int a, int b) {
                if (Y[a] != Y[b]) return Y[a] < Y[b];
                return X[a] < X[b];
            });
        }

        long long runR = 0;
        for (int kk = 1; kk < k; kk++) {
            runR += R[sorted_idx[kk - 1]];
            int leftC  = useX ? X[sorted_idx[kk - 1]] : Y[sorted_idx[kk - 1]];
            int rightC = useX ? X[sorted_idx[kk]]     : Y[sorted_idx[kk]];
            if (leftC >= rightC) continue;

            double areaRatio = (double)runR / (double)totalR;
            int lo, hi;
            double ideal;

            if (useX) {
                ideal = x1 + areaRatio * (x2 - x1);
                lo = max(x1 + 1, leftC + 1);
                hi = min(x2 - 1, rightC);
            } else {
                ideal = y1 + areaRatio * (y2 - y1);
                lo = max(y1 + 1, leftC + 1);
                hi = min(y2 - 1, rightC);
            }
            if (lo > hi) continue;

            int s = max(lo, min((int)round(ideal), hi));
            double actualRatio = useX
                ? (double)(s - x1) / (x2 - x1)
                : (double)(s - y1) / (y2 - y1);
            double cost = (areaRatio - actualRatio) * (areaRatio - actualRatio);
            if (cost < bestCost) {
                bestCost = cost;
                bestUseX = (bool)useX;
                bestSplitK = kk;
                bestSplitS = s;
                bestSorted = sorted_idx;
            }
        }
    }

    if (bestSplitK < 0) {
        int mid = k / 2;
        bool useX = (x2 - x1) >= (y2 - y1);
        vector<int> sorted_idx = indices;
        if (useX) {
            sort(sorted_idx.begin(), sorted_idx.end(), [](int a, int b) {
                if (X[a] != X[b]) return X[a] < X[b];
                return Y[a] < Y[b];
            });
        } else {
            sort(sorted_idx.begin(), sorted_idx.end(), [](int a, int b) {
                if (Y[a] != Y[b]) return Y[a] < Y[b];
                return X[a] < X[b];
            });
        }
        int sVal = useX ? (x1 + x2) / 2 : (y1 + y2) / 2;
        sVal = max((useX ? x1 : y1) + 1, min(sVal, (useX ? x2 : y2) - 1));

        vector<int> left(sorted_idx.begin(), sorted_idx.begin() + mid);
        vector<int> right(sorted_idx.begin() + mid, sorted_idx.end());
        if (useX) {
            do_partition(left,  x1,     y1, sVal, y2);
            do_partition(right, sVal,   y1, x2,   y2);
        } else {
            do_partition(left,  x1, y1,   x2, sVal);
            do_partition(right, x1, sVal, x2, y2);
        }
        return;
    }

    vector<int> left(bestSorted.begin(), bestSorted.begin() + bestSplitK);
    vector<int> right(bestSorted.begin() + bestSplitK, bestSorted.end());
    if (bestUseX) {
        do_partition(left,  x1,         y1, bestSplitS, y2);
        do_partition(right, bestSplitS, y1, x2,         y2);
    } else {
        do_partition(left,  x1, y1,         x2, bestSplitS);
        do_partition(right, x1, bestSplitS, x2, y2);
    }
}

// ---- Phase 2: Simulated annealing ----

static void sa_refine(double timeLimit) {
    mt19937 rng(12345);
    auto t0 = chrono::steady_clock::now();

    vector<double> sats(N);
    for (int i = 0; i < N; i++) sats[i] = satisfaction(i);

    auto bestRects = rects;
    double bestTotal = 0;
    for (double s : sats) bestTotal += s;
    double currentTotal = bestTotal;

    uniform_int_distribution<int> distN(0, N - 1);
    uniform_int_distribution<int> distDir(0, 3);
    uniform_real_distribution<double> dist01(0.0, 1.0);

    int iters = 0;
    double progress = 0.0;

    while (true) {
        iters++;
        if (iters % 500 == 0) {
            auto now = chrono::steady_clock::now();
            double elapsed = chrono::duration<double>(now - t0).count();
            if (elapsed >= timeLimit) break;
            progress = elapsed / timeLimit;
        }

        int i = distN(rng);
        int a = rects[i][0], b = rects[i][1], c = rects[i][2], d = rects[i][3];

        int maxDelta = max(2, (int)(300.0 * (1.0 - progress) + 5));
        uniform_int_distribution<int> distDelta(1, maxDelta);
        int bnd = distDir(rng);
        int delta = distDelta(rng);
        if (dist01(rng) < 0.5) delta = -delta;

        int na = a, nb = b, nc = c, nd = d;
        switch (bnd) {
            case 0: na += delta; break;
            case 1: nb += delta; break;
            case 2: nc += delta; break;
            case 3: nd += delta; break;
        }

        if (na >= nc || nb >= nd) continue;
        if (na < 0 || nb < 0 || nc > 10000 || nd > 10000) continue;
        if (na > X[i] || nc < X[i] + 1 || nb > Y[i] || nd < Y[i] + 1) continue;

        bool overlap = false;
        for (int j = 0; j < N; j++) {
            if (j == i) continue;
            if (na < rects[j][2] && nc > rects[j][0] &&
                nb < rects[j][3] && nd > rects[j][1]) {
                overlap = true;
                break;
            }
        }
        if (overlap) continue;

        double newS = sat_value(R[i], (nc - na) * (nd - nb));
        double ds = newS - sats[i];

        double T = 0.08 * max(0.001, 1.0 - progress);
        if (ds >= 0 || dist01(rng) < exp(ds / max(T, 1e-12))) {
            rects[i] = {na, nb, nc, nd};
            sats[i] = newS;
            currentTotal += ds;
            if (currentTotal > bestTotal) {
                bestTotal = currentTotal;
                bestRects = rects;
            }
        }
    }

    rects = bestRects;
}

// ---- Phase 3: Greedy expansion ----

static void greedy_expand() {
    vector<int> order(N);
    iota(order.begin(), order.end(), 0);
    sort(order.begin(), order.end(), [](int a, int b) {
        int sa = (rects[a][2] - rects[a][0]) * (rects[a][3] - rects[a][1]);
        int sb = (rects[b][2] - rects[b][0]) * (rects[b][3] - rects[b][1]);
        double ra = (double)R[a] / max(1, sa);
        double rb = (double)R[b] / max(1, sb);
        return ra > rb;
    });

    for (int i : order) {
        for (int dir = 0; dir < 4; dir++) {
            int a = rects[i][0], b = rects[i][1], c = rects[i][2], d = rects[i][3];
            int s = (c - a) * (d - b);
            if (s >= R[i]) break;

            if (dir == 0) { // right
                int limit = 10000;
                for (int j = 0; j < N; j++) {
                    if (j == i) continue;
                    if (rects[j][0] >= c && b < rects[j][3] && d > rects[j][1])
                        limit = min(limit, rects[j][0]);
                }
                if (limit <= c) continue;
                int needed = (R[i] - s + (d - b) - 1) / (d - b);
                int newC = min(limit, c + max(1, needed));
                int newS = (newC - a) * (d - b);
                if ((double)min(R[i], newS) / max(R[i], newS) >
                    (double)min(R[i], s) / max(R[i], s))
                    rects[i][2] = newC;
            } else if (dir == 1) { // down
                int limit = 10000;
                for (int j = 0; j < N; j++) {
                    if (j == i) continue;
                    if (rects[j][1] >= d && a < rects[j][2] && c > rects[j][0])
                        limit = min(limit, rects[j][1]);
                }
                if (limit <= d) continue;
                int needed = (R[i] - s + (c - a) - 1) / (c - a);
                int newD = min(limit, d + max(1, needed));
                int newS = (c - a) * (newD - b);
                if ((double)min(R[i], newS) / max(R[i], newS) >
                    (double)min(R[i], s) / max(R[i], s))
                    rects[i][3] = newD;
            } else if (dir == 2) { // left
                int limit = 0;
                for (int j = 0; j < N; j++) {
                    if (j == i) continue;
                    if (rects[j][2] <= a && b < rects[j][3] && d > rects[j][1])
                        limit = max(limit, rects[j][2]);
                }
                if (limit >= a) continue;
                int needed = (R[i] - s + (d - b) - 1) / (d - b);
                int newA = max(limit, a - max(1, needed));
                if (newA > X[i]) newA = min(newA, X[i]);
                int newS = (c - newA) * (d - b);
                if (newA < a && (double)min(R[i], newS) / max(R[i], newS) >
                    (double)min(R[i], s) / max(R[i], s))
                    rects[i][0] = newA;
            } else { // up
                int limit = 0;
                for (int j = 0; j < N; j++) {
                    if (j == i) continue;
                    if (rects[j][3] <= b && a < rects[j][2] && c > rects[j][0])
                        limit = max(limit, rects[j][3]);
                }
                if (limit >= b) continue;
                int needed = (R[i] - s + (c - a) - 1) / (c - a);
                int newB = max(limit, b - max(1, needed));
                if (newB > Y[i]) newB = min(newB, Y[i]);
                int newS = (c - a) * (d - newB);
                if (newB < b && (double)min(R[i], newS) / max(R[i], newS) >
                    (double)min(R[i], s) / max(R[i], s))
                    rects[i][1] = newB;
            }
        }
    }
}

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);

    cin >> N;
    X.resize(N);
    Y.resize(N);
    R.resize(N);
    rects.resize(N);

    for (int i = 0; i < N; i++) {
        cin >> X[i] >> Y[i] >> R[i];
    }

    vector<int> indices(N);
    iota(indices.begin(), indices.end(), 0);

    do_partition(indices, 0, 0, 10000, 10000);
    sa_refine(20.0);
    greedy_expand();

    for (int i = 0; i < N; i++) {
        printf("%d %d %d %d\n", rects[i][0], rects[i][1], rects[i][2], rects[i][3]);
    }

    return 0;
}
