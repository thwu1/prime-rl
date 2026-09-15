// Verify SDSL v3 installation works correctly.
#include <sdsl/suffix_arrays.hpp>
#include <sdsl/suffix_array_algorithm.hpp>
#include <iostream>
#include <string>

using namespace sdsl;

int main() {
    csa_wt<> csa;
    construct_im(csa, "abracadabra", 1);
    if (csa.size() != 12) {
        std::cerr << "FAIL: expected size=12, got " << csa.size() << std::endl;
        return 1;
    }
    auto cnt = count(csa, "abra");
    if (cnt != 2) {
        std::cerr << "FAIL: expected count=2, got " << cnt << std::endl;
        return 1;
    }
    auto txt = extract(csa, 0, 10);
    if (txt != "abracadabra") {
        std::cerr << "FAIL: extract mismatch" << std::endl;
        return 1;
    }
    std::cout << "SDSL verification passed" << std::endl;
    return 0;
}
