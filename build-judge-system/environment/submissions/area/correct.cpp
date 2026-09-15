#include <iostream>
#include <cmath>
#include <iomanip>
using namespace std;
int main() {
    int n;
    cin >> n;
    double x[1000], y[1000];
    for (int i = 0; i < n; i++) cin >> x[i] >> y[i];
    double area = 0;
    for (int i = 0; i < n; i++) {
        int j = (i + 1) % n;
        area += x[i] * y[j] - x[j] * y[i];
    }
    cout << fixed << setprecision(6) << fabs(area) / 2.0 << endl;
    return 0;
}
