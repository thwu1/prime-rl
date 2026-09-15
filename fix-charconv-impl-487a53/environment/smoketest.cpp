
// Smoke test — exercises a few basic cases.
// Build with: make -C /app

#include "charconv.hpp"
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <string>

static int g_fail = 0;

static void check(const char* name, bool ok, const char* detail = "") {
    if (ok) {
        std::printf("  PASS: %s\n", name);
    } else {
        std::printf("  FAIL: %s  %s\n", name, detail);
        ++g_fail;
    }
}

int main() {
    char buf[128];

    std::puts("=== Integer to_chars ===");

    auto r = myconv::to_chars(buf, buf + sizeof(buf), 42);
    check("to_chars(42)",
          r.ec == myconv::errc::ok && std::string(buf, r.ptr) == "42");

    r = myconv::to_chars(buf, buf + sizeof(buf), -1);
    check("to_chars(-1)",
          r.ec == myconv::errc::ok && std::string(buf, r.ptr) == "-1");

    r = myconv::to_chars(buf, buf + sizeof(buf), static_cast<long long>(INT64_MIN));
    std::string s(buf, r.ptr);
    check("to_chars(INT64_MIN)",
          r.ec == myconv::errc::ok && s == "-9223372036854775808",
          s.c_str());

    r = myconv::to_chars(buf, buf + sizeof(buf), 255, 16);
    s.assign(buf, r.ptr);
    check("to_chars(255, base16) == 'ff'",
          r.ec == myconv::errc::ok && s == "ff", s.c_str());

    std::puts("\n=== Integer from_chars ===");

    unsigned int uv = 999;
    const char* hex = "0x1a";
    auto fr = myconv::from_chars(hex, hex + 4, uv, 16);
    char msg[128];
    std::snprintf(msg, sizeof(msg), "val=%u ptr_off=%d", uv, static_cast<int>(fr.ptr - hex));
    check("from_chars('0x1a', base16) -> 0 at 'x'",
          fr.ec == myconv::errc::ok && uv == 0 && fr.ptr == hex + 1, msg);

    std::puts("\n=== Float to_chars ===");

    r = myconv::to_chars(buf, buf + sizeof(buf), 0.1);
    s.assign(buf, r.ptr);
    check("to_chars(0.1) is short",
          r.ec == myconv::errc::ok && s.size() <= 5, s.c_str());

    std::puts("\n=== Float round-trip ===");

    double orig = 3.14;
    r = myconv::to_chars(buf, buf + sizeof(buf), orig);
    if (r.ec == myconv::errc::ok) {
        double parsed = 0;
        auto fr2 = myconv::from_chars(buf, r.ptr, parsed);
        check("roundtrip(3.14)",
              fr2.ec == myconv::errc::ok && parsed == orig);
    }

    std::puts("\n=== chars_format ===");

    r = myconv::to_chars(buf, buf + sizeof(buf), 3.14, myconv::chars_format::scientific);
    s.assign(buf, r.ptr);
    check("to_chars(3.14, scientific) has 'e'",
          r.ec == myconv::errc::ok && s.find('e') != std::string::npos, s.c_str());

    std::printf("\n%d failure(s)\n", g_fail);
    return g_fail > 0 ? 1 : 0;
}
