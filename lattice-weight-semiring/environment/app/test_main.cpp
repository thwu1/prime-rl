// test_main.cpp — Randomized semiring axiom tests
//

#include "lattice_weight.h"
#include <cassert>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <vector>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static unsigned int g_seed = 42;

static int RandInt() { return rand_r(&g_seed); }

static double RandGauss() {
    double u1 = (RandInt() + 1.0) / (RAND_MAX + 2.0);
    double u2 = (RandInt() + 1.0) / (RAND_MAX + 2.0);
    return std::sqrt(-2.0 * std::log(u1)) * std::cos(2.0 * M_PI * u2);
}

static LatticeWeight RandomLatticeWeight() {
    int tmp = RandInt() % 4;
    if (tmp == 0) return LatticeWeight::Zero();
    else if (tmp == 1) return LatticeWeight(1, 2);
    else if (tmp == 2) return LatticeWeight(2, 1);
    else return LatticeWeight(static_cast<float>(100 * RandGauss()),
                              static_cast<float>(100 * RandGauss()));
}

static CompactLatticeWeight RandomCompactLatticeWeight() {
    LatticeWeight w = RandomLatticeWeight();
    if (w == LatticeWeight::Zero())
        return CompactLatticeWeight(w, std::vector<int32_t>());
    int len = RandInt() % 4;
    std::vector<int32_t> str;
    for (int i = 0; i < len; i++)
        str.push_back(RandInt() % 10 + 1);
    return CompactLatticeWeight(w, str);
}

static void AssertApproxEqualF(float a, float b, float eps, int line) {
    if (std::isinf(a) && std::isinf(b) && ((a > 0) == (b > 0))) return;
    if (std::abs(a - b) > eps) {
        std::cerr << "Float mismatch at line " << line << ": " << a
                  << " vs " << b << std::endl;
        abort();
    }
}
#define ASSERT_APPROX_F(a, b, eps) AssertApproxEqualF(a, b, eps, __LINE__)

#define ASSERT_TRUE(expr) do { \
    if (!(expr)) { \
        std::cerr << "FAILED at " << __FILE__ << ":" << __LINE__ \
                  << ": " << #expr << std::endl; \
        abort(); \
    } \
} while(0)

static void TestLatticeWeight() {
    std::cout << "Testing LatticeWeight..." << std::endl;
    for (int iter = 0; iter < 100; iter++) {
        LatticeWeight l1 = RandomLatticeWeight(), l2 = RandomLatticeWeight();
        LatticeWeight l3 = Plus(l1, l2);
        LatticeWeight l4 = Times(l1, l2);

        float f1 = l1.Value1() + l1.Value2();
        float f2 = l2.Value1() + l2.Value2();
        float f3 = l3.Value1() + l3.Value2();
        float f4 = l4.Value1() + l4.Value2();

        // Plus takes min total cost
        ASSERT_APPROX_F(std::min(f1, f2), f3, 0.01f);

        // Times adds costs
        if (!std::isinf(f1) && !std::isinf(f2))
            ASSERT_APPROX_F(f1 + f2, f4, 0.01f);

        // Idempotent Plus
        ASSERT_TRUE(Plus(l3, l3) == l3);
        // Commutativity
        ASSERT_TRUE(Plus(l1, l2) == Plus(l2, l1));
        ASSERT_TRUE(Times(l1, l2) == Times(l2, l1));
        // Identity
        ASSERT_TRUE(Plus(l3, LatticeWeight::Zero()) == l3);
        ASSERT_TRUE(Times(l3, LatticeWeight::One()) == l3);
        // Annihilation
        ASSERT_TRUE(Times(l3, LatticeWeight::Zero()) == LatticeWeight::Zero());

        // Reverse
        ASSERT_TRUE(l3.Reverse().Reverse() == l3);

        // NaturalLess consistency
        NaturalLess<LatticeWeight> nl;
        bool a = nl(l1, l2);
        bool b = (Plus(l1, l2) == l1 && l1 != l2);
        ASSERT_TRUE(a == b);

        // Compare consistency with Plus
        ASSERT_TRUE(Compare(l1, Plus(l1, l2)) != 1);

        // Distributivity (approximate)
        LatticeWeight l5 = RandomLatticeWeight(), l6 = RandomLatticeWeight();
        {
            LatticeWeight wa = Times(Plus(l1, l2), Plus(l5, l6));
            LatticeWeight wb = Plus(Times(l1, l5),
                               Plus(Times(l1, l6),
                               Plus(Times(l2, l5), Times(l2, l6))));
            ASSERT_TRUE(ApproxEqual(wa, wb));
        }

        // Member
        ASSERT_TRUE(l1.Member());
        ASSERT_TRUE(l2.Member());
        ASSERT_TRUE(l3.Member());
        ASSERT_TRUE(l4.Member());
        LatticeWeight l5b = RandomLatticeWeight(), l6b = RandomLatticeWeight();
        ASSERT_TRUE(l5b.Member());
        ASSERT_TRUE(l6b.Member());

        // Divide
        if (l2 != LatticeWeight::Zero())
            ASSERT_TRUE(ApproxEqual(Divide(Times(l1, l2), l2), l1));

        // Quantize
        ASSERT_TRUE(ApproxEqual(l1, l1.Quantize()));

        // Text I/O round-trip
        {
            std::ostringstream s1;
            s1 << l1;
            std::istringstream s2(s1.str());
            LatticeWeight l1_read;
            s2 >> l1_read;
            ASSERT_TRUE(ApproxEqual(l1, l1_read, 0.001f));
        }

        // Binary I/O round-trip
        {
            std::ostringstream s1b;
            l1.Write(s1b);
            std::istringstream s2b(s1b.str());
            LatticeWeight l3b;
            l3b.Read(s2b);
            ASSERT_TRUE(l1 == l3b);
        }
    }
    std::cout << "  LatticeWeight tests passed." << std::endl;
}

static void TestCompactLatticeWeight() {
    std::cout << "Testing CompactLatticeWeight..." << std::endl;
    for (int iter = 0; iter < 100; iter++) {
        CompactLatticeWeight l1 = RandomCompactLatticeWeight();
        CompactLatticeWeight l2 = RandomCompactLatticeWeight();
        CompactLatticeWeight l3 = Plus(l1, l2);
        CompactLatticeWeight l4 = Times(l1, l2);

        // Idempotent Plus
        ASSERT_TRUE(Plus(l3, l3) == l3);
        // Commutativity of Plus
        ASSERT_TRUE(Plus(l1, l2) == Plus(l2, l1));
        // Identity
        ASSERT_TRUE(Plus(l3, CompactLatticeWeight::Zero()) == l3);
        ASSERT_TRUE(Times(l3, CompactLatticeWeight::One()) == l3);
        // Annihilation
        ASSERT_TRUE(Times(l3, CompactLatticeWeight::Zero()) ==
                    CompactLatticeWeight::Zero());

        // NaturalLess consistency
        NaturalLess<CompactLatticeWeight> nl;
        bool a = nl(l1, l2);
        bool b = (Plus(l1, l2) == l1 && l1 != l2);
        ASSERT_TRUE(a == b);

        // Compare consistency
        ASSERT_TRUE(Compare(l1, Plus(l1, l2)) != 1);

        // Distributivity (exact!)
        CompactLatticeWeight l5 = RandomCompactLatticeWeight();
        CompactLatticeWeight l6 = RandomCompactLatticeWeight();
        ASSERT_TRUE(Times(Plus(l1, l2), Plus(l5, l6)) ==
                    Plus(Times(l1, l5),
                    Plus(Times(l1, l6),
                    Plus(Times(l2, l5), Times(l2, l6)))));

        // Member
        ASSERT_TRUE(l1.Member());
        ASSERT_TRUE(l2.Member());
        ASSERT_TRUE(l3.Member());
        ASSERT_TRUE(l4.Member());
        ASSERT_TRUE(l5.Member());
        ASSERT_TRUE(l6.Member());

        // Divide
        if (l2 != CompactLatticeWeight::Zero()) {
            ASSERT_TRUE(ApproxEqual(Divide(Times(l1, l2), l2, DIVIDE_RIGHT), l1));
            ASSERT_TRUE(ApproxEqual(Divide(Times(l2, l1), l2, DIVIDE_LEFT), l1));
        }

        // Quantize
        ASSERT_TRUE(ApproxEqual(l1, l1.Quantize()));

        // Text I/O round-trip
        {
            std::ostringstream s1;
            s1 << l1;
            std::istringstream s2(s1.str());
            CompactLatticeWeight l1_read;
            s2 >> l1_read;
            ASSERT_TRUE(ApproxEqual(l1, l1_read));
        }

        // Binary I/O round-trip
        {
            std::ostringstream s1b;
            l1.Write(s1b);
            std::istringstream s2b(s1b.str());
            CompactLatticeWeight l3b;
            l3b.Read(s2b);
            ASSERT_TRUE(l1 == l3b);
        }

        // CommonDivisor
        CompactLatticeWeightCommonDivisor divisor;
        CompactLatticeWeight cd = divisor(l5, l6);
        if (cd != CompactLatticeWeight::Zero()) {
            CompactLatticeWeight rem1 = Divide(l5, cd, DIVIDE_LEFT);
            CompactLatticeWeight rem2 = Divide(l6, cd, DIVIDE_LEFT);
            CompactLatticeWeight cd2 = divisor(rem1, rem2);
            ASSERT_TRUE(ApproxEqual(cd2, CompactLatticeWeight::One()));
        } else {
            ASSERT_TRUE(l5 == CompactLatticeWeight::Zero() &&
                        l6 == CompactLatticeWeight::Zero());
        }
    }
    std::cout << "  CompactLatticeWeight tests passed." << std::endl;
}

static void TestLatticeStringRepository() {
    std::cout << "Testing LatticeStringRepository..." << std::endl;
    LatticeStringRepository<int32_t> sr;
    typedef LatticeStringRepository<int32_t>::Entry Entry;

    for (int iter = 0; iter < 100; iter++) {
        int len = RandInt() % 5;
        std::vector<int32_t> str(len), str2;
        const Entry* e = nullptr;
        for (int j = 0; j < len; j++) {
            str[j] = RandInt() % 5;
            e = sr.Successor(e, str[j]);
        }
        sr.ConvertToVector(e, &str2);
        ASSERT_TRUE(str == str2);

        int len2 = RandInt() % 5;
        str2.resize(len2);
        const Entry* f = sr.EmptyString();
        for (int j = 0; j < len2; j++) {
            str2[j] = RandInt() % 5;
            f = sr.Successor(f, str2[j]);
        }

        // Compute expected prefix
        std::vector<int32_t> prefix;
        for (int j = 0; j < len && j < len2; j++) {
            if (str[j] == str2[j]) prefix.push_back(str[j]);
            else break;
        }

        // CommonPrefix
        const Entry* g = sr.CommonPrefix(e, f);
        std::vector<int32_t> prefix2;
        sr.ConvertToVector(g, &prefix2);
        ASSERT_TRUE(prefix == prefix2);

        // ReduceToCommonPrefix
        std::vector<int32_t> prefix3;
        sr.ConvertToVector(e, &prefix3);
        sr.ReduceToCommonPrefix(f, &prefix3);
        ASSERT_TRUE(prefix == prefix3);

        // IsPrefixOf
        ASSERT_TRUE(sr.IsPrefixOf(g, e));
        ASSERT_TRUE(sr.IsPrefixOf(g, f));
        if (static_cast<int>(str.size()) > static_cast<int>(prefix.size()))
            ASSERT_TRUE(!sr.IsPrefixOf(e, g));

        // Size
        ASSERT_TRUE(sr.Size(e) == static_cast<size_t>(len));
        ASSERT_TRUE(sr.Size(f) == static_cast<size_t>(len2));
        ASSERT_TRUE(sr.Size(g) == prefix.size());

        // ConvertFromVector
        const Entry* e2 = sr.ConvertFromVector(str);
        std::vector<int32_t> str3;
        sr.ConvertToVector(e2, &str3);
        ASSERT_TRUE(str == str3);

        // Concatenate
        const Entry* cat = sr.Concatenate(e, f);
        std::vector<int32_t> cat_vec;
        sr.ConvertToVector(cat, &cat_vec);
        std::vector<int32_t> expected_cat = str;
        expected_cat.insert(expected_cat.end(), str2.begin(), str2.end());
        ASSERT_TRUE(cat_vec == expected_cat);

        // RemovePrefix
        if (!prefix.empty()) {
            const Entry* rem = sr.RemovePrefix(e, prefix.size());
            std::vector<int32_t> rem_vec;
            sr.ConvertToVector(rem, &rem_vec);
            std::vector<int32_t> expected_rem(str.begin() +
                static_cast<int>(prefix.size()), str.end());
            ASSERT_TRUE(rem_vec == expected_rem);
        }
    }

    // Test Rebuild: create many entries, keep subset, verify survivors
    {
        LatticeStringRepository<int32_t> sr2;
        std::vector<const Entry*> entries;
        for (int i = 0; i < 50; i++) {
            int len = RandInt() % 5;
            const Entry* e = nullptr;
            for (int j = 0; j < len; j++)
                e = sr2.Successor(e, RandInt() % 5);
            if (i < 10) entries.push_back(e);
        }
        int old_size = sr2.MemSize();
        sr2.Rebuild(entries);
        int new_size = sr2.MemSize();
        ASSERT_TRUE(new_size <= old_size);
        for (const auto* e : entries) {
            std::vector<int32_t> v;
            sr2.ConvertToVector(e, &v);
            // verify round-trip after rebuild
            const Entry* e2 = sr2.ConvertFromVector(v);
            std::vector<int32_t> v2;
            sr2.ConvertToVector(e2, &v2);
            ASSERT_TRUE(v == v2);
        }
    }

    std::cout << "  LatticeStringRepository tests passed." << std::endl;
}

int main() {
    TestLatticeWeight();
    TestCompactLatticeWeight();
    TestLatticeStringRepository();
    std::cout << "All tests passed!" << std::endl;
    return 0;
}
