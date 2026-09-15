#include "testlib.h"
#include <vector>
#include <algorithm>
using namespace std;

int main(int argc, char* argv[]) {
    registerTestlibCmd(argc, argv);

    int n = inf.readInt();
    vector<int> a(n);
    for (int i = 0; i < n; i++) a[i] = inf.readInt();

    vector<int> result;
    for (int i = 0; i < n; i++) {
        result.push_back(ouf.readInt());
    }

    // Must be a permutation of the input array
    vector<int> sa = a, sr = result;
    sort(sa.begin(), sa.end());
    sort(sr.begin(), sr.end());
    if (sa != sr)
        quitf(_wa, "output is not a permutation of input");

    // Must be a derangement: no element at its original position
    for (int i = 0; i < n; i++) {
        if (result[i] == a[i])
            quitf(_wa, "position %d has same element as input", i + 1);
    }

    quitf(_ok, "valid derangement of %d elements", n);
}
