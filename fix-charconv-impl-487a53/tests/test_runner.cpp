
// Comprehensive conformance test runner for the myconv charconv library.
// Outputs lines: "PASS test_name" or "FAIL test_name detail..."
// Exit code: 0 if all pass, 1 otherwise.

#include "charconv.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <cmath>
#include <climits>
#include <cfloat>
#include <string>
#include <limits>
#include <fstream>

static int g_fail = 0;
static int g_pass = 0;

static void pass(const char* name) {
    std::printf("PASS %s\n", name);
    ++g_pass;
}
static void fail(const char* name, const char* detail) {
    std::printf("FAIL %s %s\n", name, detail);
    ++g_fail;
}

#define CHECK(name, cond, ...) do { \
    if (cond) { pass(name); } else { \
        char _msg[512]; std::snprintf(_msg, sizeof(_msg), __VA_ARGS__); \
        fail(name, _msg); \
    } \
} while(0)

// --- Helpers ---

static std::string tc(long long val, int base = 10) {
    char buf[128];
    auto r = myconv::to_chars(buf, buf + sizeof(buf), val, base);
    if (r.ec != myconv::errc::ok) return "<ERR>";
    return std::string(buf, r.ptr);
}
static std::string tc_ull(unsigned long long val, int base = 10) {
    char buf[128];
    auto r = myconv::to_chars(buf, buf + sizeof(buf), val, base);
    if (r.ec != myconv::errc::ok) return "<ERR>";
    return std::string(buf, r.ptr);
}
static std::string tc_dbl(double val) {
    char buf[128];
    auto r = myconv::to_chars(buf, buf + sizeof(buf), val);
    if (r.ec != myconv::errc::ok) return "<ERR>";
    return std::string(buf, r.ptr);
}
static std::string tc_flt(float val) {
    char buf[128];
    auto r = myconv::to_chars(buf, buf + sizeof(buf), val);
    if (r.ec != myconv::errc::ok) return "<ERR>";
    return std::string(buf, r.ptr);
}
static std::string tc_fmt(double val, myconv::chars_format fmt) {
    char buf[256];
    auto r = myconv::to_chars(buf, buf + sizeof(buf), val, fmt);
    if (r.ec != myconv::errc::ok) return "<ERR>";
    return std::string(buf, r.ptr);
}
static std::string tc_fmtp(double val, myconv::chars_format fmt, int prec) {
    char buf[512];
    auto r = myconv::to_chars(buf, buf + sizeof(buf), val, fmt, prec);
    if (r.ec != myconv::errc::ok) return "<ERR>";
    return std::string(buf, r.ptr);
}

// ===================================================================
// Integer to_chars tests
// ===================================================================

static void test_int_to_chars() {
    CHECK("int_to_chars_0", tc(0) == "0", "got '%s'", tc(0).c_str());
    CHECK("int_to_chars_42", tc(42) == "42", "got '%s'", tc(42).c_str());
    CHECK("int_to_chars_neg42", tc(-42) == "-42", "got '%s'", tc(-42).c_str());

    CHECK("int_to_chars_int64_min",
          tc(static_cast<long long>(INT64_MIN)) == "-9223372036854775808",
          "got '%s'", tc(static_cast<long long>(INT64_MIN)).c_str());

    {
        char buf[128];
        auto r = myconv::to_chars(buf, buf + sizeof(buf), static_cast<int>(INT32_MIN));
        std::string s(buf, r.ptr);
        CHECK("int_to_chars_int32_min",
              r.ec == myconv::errc::ok && s == "-2147483648",
              "got '%s'", s.c_str());
    }

    CHECK("int_to_chars_hex_ff",
          tc(255, 16) == "ff",
          "got '%s'", tc(255, 16).c_str());

    CHECK("int_to_chars_hex_deadbeef",
          tc_ull(0xdeadbeefULL, 16) == "deadbeef",
          "got '%s'", tc_ull(0xdeadbeefULL, 16).c_str());

    CHECK("int_to_chars_base36_z",
          tc(35, 36) == "z",
          "got '%s'", tc(35, 36).c_str());

    // Buffer overflow
    {
        char buf[3];
        auto r = myconv::to_chars(buf, buf + 3, 1000);
        CHECK("int_to_chars_buf_overflow",
              r.ec == myconv::errc::value_too_large && r.ptr == buf + 3,
              "ec=%d ptr_off=%d", static_cast<int>(r.ec),
              static_cast<int>(r.ptr - buf));
    }
    {
        char buf[4];
        auto r = myconv::to_chars(buf, buf + 4, 1000);
        std::string s(buf, r.ptr);
        CHECK("int_to_chars_buf_exact_fit",
              r.ec == myconv::errc::ok && s == "1000",
              "ec=%d got='%s'", static_cast<int>(r.ec), s.c_str());
    }
}

// ===================================================================
// Integer from_chars tests
// ===================================================================

static void test_int_from_chars() {
    // Basic parsing
    {
        int val = 0;
        const char* s = "42";
        auto r = myconv::from_chars(s, s + 2, val);
        CHECK("int_from_chars_42",
              r.ec == myconv::errc::ok && val == 42 && r.ptr == s + 2,
              "val=%d ec=%d", val, static_cast<int>(r.ec));
    }
    {
        int val = 0;
        const char* s = "-99abc";
        auto r = myconv::from_chars(s, s + 6, val);
        CHECK("int_from_chars_neg99",
              r.ec == myconv::errc::ok && val == -99 && r.ptr == s + 3,
              "val=%d ptr_off=%d", val, static_cast<int>(r.ptr - s));
    }

    // No 0x prefix for base 16
    {
        unsigned int val = 999;
        const char* s = "0x1a";
        auto r = myconv::from_chars(s, s + 4, val, 16);
        CHECK("int_from_chars_no_0x",
              r.ec == myconv::errc::ok && val == 0 && r.ptr == s + 1,
              "val=%u ptr_off=%d ec=%d", val,
              static_cast<int>(r.ptr - s), static_cast<int>(r.ec));
    }

    // Overflow detection for unsigned long long
    {
        unsigned long long val = 42;
        const char* s = "18446744073709551616"; // ULLONG_MAX + 1
        auto r = myconv::from_chars(s, s + std::strlen(s), val, 10);
        CHECK("int_from_chars_ull_overflow",
              r.ec == myconv::errc::result_out_of_range && val == 42,
              "ec=%d val=%llu", static_cast<int>(r.ec), val);
    }
    {
        unsigned long long val = 0;
        const char* s = "18446744073709551615"; // ULLONG_MAX
        auto r = myconv::from_chars(s, s + std::strlen(s), val, 10);
        CHECK("int_from_chars_ull_max_ok",
              r.ec == myconv::errc::ok && val == ULLONG_MAX,
              "ec=%d val=%llu", static_cast<int>(r.ec), val);
    }

    // Integer round-trip for various bases
    auto roundtrip = [](long long v, int base, const char* tname) {
        char buf[128];
        auto r1 = myconv::to_chars(buf, buf + sizeof(buf), v, base);
        if (r1.ec != myconv::errc::ok) {
            fail(tname, "to_chars failed");
            return;
        }
        long long parsed = 0;
        auto r2 = myconv::from_chars(buf, r1.ptr, parsed, base);
        CHECK(tname, r2.ec == myconv::errc::ok && parsed == v,
              "orig=%lld parsed=%lld base=%d str='%.*s'",
              v, parsed, base, static_cast<int>(r1.ptr - buf), buf);
    };

    roundtrip(1234567890LL, 10, "int_roundtrip_base10");
    roundtrip(0xCAFELL, 16, "int_roundtrip_base16");
    roundtrip(255LL, 2, "int_roundtrip_base2");
    roundtrip(123456LL, 36, "int_roundtrip_base36");
}

// ===================================================================
// Float to_chars tests (double, shortest)
// ===================================================================

static void test_float_to_chars() {
    // Shortest representation checks
    {
        std::string s = tc_dbl(0.1);
        CHECK("float_to_chars_0.1_short",
              s.size() <= 5,
              "got '%s' len=%zu (expected <=5)", s.c_str(), s.size());
    }
    {
        std::string s = tc_dbl(3.14);
        CHECK("float_to_chars_3.14_short",
              s.size() <= 6,
              "got '%s' len=%zu (expected <=6)", s.c_str(), s.size());
    }

    // Round-trip checks
    auto rt = [](double v, const char* name) {
        char buf[128];
        auto r1 = myconv::to_chars(buf, buf + sizeof(buf), v);
        if (r1.ec != myconv::errc::ok) {
            fail(name, "to_chars failed");
            return;
        }
        double parsed = -12345.6789;
        auto r2 = myconv::from_chars(buf, r1.ptr, parsed);
        if (r2.ec != myconv::errc::ok) {
            char msg[256];
            std::snprintf(msg, sizeof(msg),
                "from_chars failed on '%.*s'",
                static_cast<int>(r1.ptr - buf), buf);
            fail(name, msg);
            return;
        }
        // Bit-exact comparison (handles -0.0 vs 0.0)
        bool ok = (std::memcmp(&v, &parsed, sizeof(double)) == 0);
        CHECK(name, ok,
              "orig=%a parsed=%a str='%.*s'",
              v, parsed, static_cast<int>(r1.ptr - buf), buf);
    };

    rt(0.1, "float_rt_0.1");
    rt(0.3, "float_rt_0.3");
    rt(3.14, "float_rt_3.14");
    rt(1e10, "float_rt_1e10");
    rt(1e-10, "float_rt_1e-10");
    rt(1.7976931348623157e+308, "float_rt_dbl_max");
    rt(2.2250738585072014e-308, "float_rt_dbl_min");
    rt(-3.141592653589793, "float_rt_neg_pi");

    // Special values
    {
        std::string s = tc_dbl(0.0);
        CHECK("float_to_chars_zero",
              s == "0" || s == "0.0" || s == "0e0" || s == "0e+0" || s == "0e+00",
              "got '%s'", s.c_str());
    }
    {
        std::string s = tc_dbl(-0.0);
        CHECK("float_to_chars_neg_zero",
              s.size() >= 2 && s[0] == '-',
              "got '%s'", s.c_str());
    }
    {
        std::string s = tc_dbl(std::numeric_limits<double>::infinity());
        CHECK("float_to_chars_inf",
              s == "inf" || s == "Inf" || s == "INF",
              "got '%s'", s.c_str());
    }
    {
        std::string s = tc_dbl(-std::numeric_limits<double>::infinity());
        CHECK("float_to_chars_neg_inf",
              s == "-inf" || s == "-Inf" || s == "-INF",
              "got '%s'", s.c_str());
    }
    {
        std::string s = tc_dbl(std::numeric_limits<double>::quiet_NaN());
        CHECK("float_to_chars_nan",
              s == "nan" || s == "NaN" || s == "NAN",
              "got '%s'", s.c_str());
    }
}

// ===================================================================
// Float from_chars tests (double)
// ===================================================================

static void test_float_from_chars() {
    // Reject leading whitespace
    {
        double val = 999.0;
        const char* s = " 1.0";
        auto r = myconv::from_chars(s, s + 4, val);
        CHECK("float_from_chars_no_ws",
              r.ec == myconv::errc::invalid_argument && val == 999.0,
              "ec=%d val=%g", static_cast<int>(r.ec), val);
    }

    // Reject '+' sign
    {
        double val = 999.0;
        const char* s = "+1.0";
        auto r = myconv::from_chars(s, s + 4, val);
        CHECK("float_from_chars_no_plus",
              r.ec == myconv::errc::invalid_argument && val == 999.0,
              "ec=%d val=%g", static_cast<int>(r.ec), val);
    }

    // No 0x prefix — parse '0' and stop at 'x'
    {
        double val = 999.0;
        const char* s = "0x1p0";
        auto r = myconv::from_chars(s, s + 5, val);
        CHECK("float_from_chars_no_0x",
              r.ec == myconv::errc::ok && val == 0.0 && r.ptr == s + 1,
              "ec=%d val=%g ptr_off=%d",
              static_cast<int>(r.ec), val, static_cast<int>(r.ptr - s));
    }

    // Must respect [first, last) boundary
    {
        double val = 999.0;
        const char* s = "1.5e10";
        // Parse only "1.5" (last = s+3, before the 'e')
        auto r = myconv::from_chars(s, s + 3, val);
        CHECK("float_from_chars_respects_last",
              r.ec == myconv::errc::ok && val == 1.5 && r.ptr == s + 3,
              "ec=%d val=%g ptr_off=%d (expected 3)",
              static_cast<int>(r.ec), val, static_cast<int>(r.ptr - s));
    }

    // Overflow returns result_out_of_range
    {
        double val = 0.0;
        const char* s = "1e999";
        auto r = myconv::from_chars(s, s + 5, val);
        CHECK("float_from_chars_overflow",
              r.ec == myconv::errc::result_out_of_range,
              "ec=%d val=%g (expected result_out_of_range)",
              static_cast<int>(r.ec), val);
    }
}

// ===================================================================
// Float type-specific tests (float32)
// ===================================================================

static void test_float32_specific() {
    // float to_chars must produce short output specific to float precision
    {
        std::string s = tc_flt(0.1f);
        CHECK("float32_to_chars_short",
              s.size() <= 4,
              "got '%s' len=%zu (expected <=4 for float)", s.c_str(), s.size());
    }

    // float round-trip
    {
        char buf[128];
        float f = 0.1f;
        auto r1 = myconv::to_chars(buf, buf + sizeof(buf), f);
        if (r1.ec != myconv::errc::ok) {
            fail("float32_rt_0.1f", "to_chars failed");
        } else {
            float parsed = -1.0f;
            auto r2 = myconv::from_chars(buf, r1.ptr, parsed);
            bool ok = (std::memcmp(&f, &parsed, sizeof(float)) == 0);
            CHECK("float32_rt_0.1f", r2.ec == myconv::errc::ok && ok,
                  "orig=%a parsed=%a str='%.*s'",
                  static_cast<double>(f), static_cast<double>(parsed),
                  static_cast<int>(r1.ptr - buf), buf);
        }
    }

    // float from_chars must detect overflow for values outside float range
    {
        float fval = 0.0f;
        const char* s = "1e39";
        auto r = myconv::from_chars(s, s + 4, fval);
        CHECK("float32_from_chars_overflow",
              r.ec == myconv::errc::result_out_of_range,
              "ec=%d fval=%g (expected result_out_of_range)",
              static_cast<int>(r.ec), static_cast<double>(fval));
    }
}

// ===================================================================
// chars_format to_chars tests
// ===================================================================

static void test_fmt_to_chars() {
    // Scientific format must contain 'e'
    {
        std::string s = tc_fmt(3.14, myconv::chars_format::scientific);
        CHECK("fmt_tc_scientific",
              s != "<ERR>" && s.find('e') != std::string::npos,
              "got '%s'", s.c_str());
    }

    // Fixed format must NOT contain 'e' or 'E'
    {
        std::string s = tc_fmt(3.14, myconv::chars_format::fixed);
        CHECK("fmt_tc_fixed",
              s != "<ERR>" &&
              s.find('e') == std::string::npos &&
              s.find('E') == std::string::npos,
              "got '%s'", s.c_str());
    }

    // Hex format: no "0x" prefix, must contain 'p'
    {
        std::string s = tc_fmt(1.0, myconv::chars_format::hex);
        CHECK("fmt_tc_hex_format",
              s != "<ERR>" &&
              s.find("0x") == std::string::npos &&
              s.find("0X") == std::string::npos &&
              (s.find('p') != std::string::npos || s.find('P') != std::string::npos),
              "got '%s'", s.c_str());
    }

    // Hex round-trip: to_chars(hex) -> from_chars(hex) should recover value
    {
        double v = 3.14;
        char buf[128];
        auto r1 = myconv::to_chars(buf, buf + sizeof(buf), v, myconv::chars_format::hex);
        if (r1.ec != myconv::errc::ok) {
            fail("fmt_tc_hex_rt", "to_chars(hex) failed");
        } else {
            double parsed = 0;
            auto r2 = myconv::from_chars(buf, r1.ptr, parsed, myconv::chars_format::hex);
            bool ok = (std::memcmp(&v, &parsed, sizeof(double)) == 0);
            CHECK("fmt_tc_hex_rt",
                  r2.ec == myconv::errc::ok && ok,
                  "orig=%a parsed=%a str='%.*s'",
                  v, parsed, static_cast<int>(r1.ptr - buf), buf);
        }
    }
}

// ===================================================================
// chars_format to_chars with precision tests
// ===================================================================

static void test_fmt_to_chars_prec() {
    // Scientific with precision 2
    {
        std::string s = tc_fmtp(3.14159, myconv::chars_format::scientific, 2);
        CHECK("fmt_tc_sci_prec",
              s == "3.14e+00",
              "got '%s' expected '3.14e+00'", s.c_str());
    }

    // Fixed with precision 3
    {
        std::string s = tc_fmtp(3.14159, myconv::chars_format::fixed, 3);
        CHECK("fmt_tc_fixed_prec",
              s == "3.142",
              "got '%s' expected '3.142'", s.c_str());
    }

    // Hex with precision 1: 1.5 = 0x1.8p+0, stripped = "1.8p+0"
    {
        std::string s = tc_fmtp(1.5, myconv::chars_format::hex, 1);
        CHECK("fmt_tc_hex_prec",
              s == "1.8p+0",
              "got '%s' expected '1.8p+0'", s.c_str());
    }

    // General with precision 4
    {
        std::string s = tc_fmtp(3.14159, myconv::chars_format::general, 4);
        CHECK("fmt_tc_general_prec",
              s == "3.142",
              "got '%s' expected '3.142'", s.c_str());
    }
}

// ===================================================================
// chars_format from_chars tests
// ===================================================================

static void test_fmt_from_chars() {
    // Scientific requires exponent: "3.14" without exponent -> invalid_argument
    {
        double val = 999.0;
        const char* s = "3.14";
        auto r = myconv::from_chars(s, s + 4, val, myconv::chars_format::scientific);
        CHECK("fmt_fc_sci_requires_exp",
              r.ec == myconv::errc::invalid_argument && val == 999.0,
              "ec=%d val=%g", static_cast<int>(r.ec), val);
    }

    // Scientific with exponent present: "3.14e2" -> 314.0
    {
        double val = 999.0;
        const char* s = "3.14e2";
        auto r = myconv::from_chars(s, s + 6, val, myconv::chars_format::scientific);
        CHECK("fmt_fc_sci_accepts_exp",
              r.ec == myconv::errc::ok && val == 314.0 && r.ptr == s + 6,
              "ec=%d val=%g ptr_off=%d",
              static_cast<int>(r.ec), val, static_cast<int>(r.ptr - s));
    }

    // Fixed stops at exponent: "3.14e2" with fixed -> parse "3.14", stop at 'e'
    {
        double val = 999.0;
        const char* s = "3.14e2";
        auto r = myconv::from_chars(s, s + 6, val, myconv::chars_format::fixed);
        CHECK("fmt_fc_fixed_stops_at_exp",
              r.ec == myconv::errc::ok && val == 3.14 && r.ptr == s + 4,
              "ec=%d val=%g ptr_off=%d",
              static_cast<int>(r.ec), val, static_cast<int>(r.ptr - s));
    }

    // Hex float parsing: "1.8p+1" = 0x1.8 * 2^1 = 3.0
    {
        double val = 999.0;
        const char* s = "1.8p+1";
        auto r = myconv::from_chars(s, s + 6, val, myconv::chars_format::hex);
        CHECK("fmt_fc_hex_parse",
              r.ec == myconv::errc::ok && val == 3.0,
              "ec=%d val=%g (expected 3.0)",
              static_cast<int>(r.ec), val);
    }

    // General accepts both with and without exponent
    {
        double val1 = 999.0;
        const char* s1 = "3.14";
        auto r1 = myconv::from_chars(s1, s1 + 4, val1, myconv::chars_format::general);

        double val2 = 999.0;
        const char* s2 = "3.14e2";
        auto r2 = myconv::from_chars(s2, s2 + 6, val2, myconv::chars_format::general);

        CHECK("fmt_fc_general_both",
              r1.ec == myconv::errc::ok && val1 == 3.14 &&
              r2.ec == myconv::errc::ok && val2 == 314.0,
              "v1=%g e1=%d v2=%g e2=%d",
              val1, static_cast<int>(r1.ec),
              val2, static_cast<int>(r2.ec));
    }
}

// ===================================================================
// Check that <charconv> header is not used
// ===================================================================

static void test_no_charconv_header() {
    std::ifstream f("/app/charconv.cpp");
    std::string line;
    bool found = false;
    while (std::getline(f, line)) {
        if (line.find("//") == 0) continue;
        if (line.find("#include <charconv>") != std::string::npos ||
            line.find("#include<charconv>") != std::string::npos) {
            found = true;
            break;
        }
    }
    CHECK("no_charconv_header", !found,
          "charconv.cpp must not #include <charconv>");
}

// ===================================================================

int main() {
    test_int_to_chars();
    test_int_from_chars();
    test_float_to_chars();
    test_float_from_chars();
    test_float32_specific();
    test_fmt_to_chars();
    test_fmt_to_chars_prec();
    test_fmt_from_chars();
    test_no_charconv_header();

    std::printf("\n%d passed, %d failed\n", g_pass, g_fail);
    return g_fail > 0 ? 1 : 0;
}
