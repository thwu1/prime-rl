/*
 * solver_template.cpp — Starter template for the Rectangle Ad Placement solver.
 *
 * This compiles and produces valid output, but scores very low (tiny 1x1 rectangles).
 * Replace the solver logic with your own optimization algorithm.
 *
 * Build:  make -C /app
 * Run:    /app/solver < /app/testcases/case_0.txt
 * Score:  python3 /app/scorer.py /app/testcases/case_0.txt /dev/stdin <<< "$(/app/solver < /app/testcases/case_0.txt)"
 */
#include <iostream>
#include <vector>
using namespace std;

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(nullptr);

    int n;
    cin >> n;

    vector<int> x(n), y(n), r(n);
    for (int i = 0; i < n; i++) {
        cin >> x[i] >> y[i] >> r[i];
    }

    // Baseline: 1x1 rectangle around each desired point.
    // This is valid but scores near zero — replace with your algorithm.
    for (int i = 0; i < n; i++) {
        cout << x[i] << " " << y[i] << " " << (x[i] + 1) << " " << (y[i] + 1) << "\n";
    }

    return 0;
}
