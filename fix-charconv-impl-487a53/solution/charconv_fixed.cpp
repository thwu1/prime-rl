
// Fixed implementation of the myconv charconv library.
// All conformance defects corrected; chars_format overloads implemented.

#include "charconv.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <cerrno>
#include <climits>
#include <cfloat>
#include <limits>
#include <type_traits>

namespace myconv {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static char digit_to_char(int d) {
    if (d < 10) return static_cast<char>('0' + d);
    // FIX: lowercase a-z
    return static_cast<char>('a' + (d - 10));
}

static int char_to_digit(char c, int base) {
    int d;
    if (c >= '0' && c <= '9')
        d = c - '0';
    else if (c >= 'a' && c <= 'z')
        d = c - 'a' + 10;
    else if (c >= 'A' && c <= 'Z')
        d = c - 'A' + 10;
    else
        return -1;
    return (d < base) ? d : -1;
}

static bool is_hex_digit(char c) {
    return (c >= '0' && c <= '9') ||
           (c >= 'a' && c <= 'f') ||
           (c >= 'A' && c <= 'F');
}

// ---------------------------------------------------------------------------
// Integer to_chars
// ---------------------------------------------------------------------------

template <typename T>
static to_chars_result to_chars_unsigned_impl(char* first, char* last, T value, int base) {
    char buf[65];
    int pos = 0;

    if (value == 0) {
        if (first >= last) return {last, errc::value_too_large};
        *first = '0';
        return {first + 1, errc::ok};
    }

    while (value > 0) {
        buf[pos++] = digit_to_char(static_cast<int>(value % static_cast<T>(base)));
        value /= static_cast<T>(base);
    }

    if (pos > static_cast<int>(last - first)) {
        return {last, errc::value_too_large};
    }

    for (int i = 0; i < pos; ++i) {
        first[i] = buf[pos - 1 - i];
    }

    return {first + pos, errc::ok};
}

template <typename T>
static to_chars_result to_chars_signed_impl(char* first, char* last, T value, int base) {
    using UT = typename std::make_unsigned<T>::type;

    if (value >= 0) {
        return to_chars_unsigned_impl<UT>(first, last, static_cast<UT>(value), base);
    }

    if (first >= last) return {last, errc::value_too_large};
    *first++ = '-';

    // FIX: unsigned two's complement negation handles all values including min()
    UT uval = static_cast<UT>(0) - static_cast<UT>(value);
    return to_chars_unsigned_impl<UT>(first, last, uval, base);
}

// Explicit instantiations
to_chars_result to_chars(char* f, char* l, signed char v, int b)    { return to_chars_signed_impl(f, l, v, b); }
to_chars_result to_chars(char* f, char* l, short v, int b)          { return to_chars_signed_impl(f, l, v, b); }
to_chars_result to_chars(char* f, char* l, int v, int b)            { return to_chars_signed_impl(f, l, v, b); }
to_chars_result to_chars(char* f, char* l, long v, int b)           { return to_chars_signed_impl(f, l, v, b); }
to_chars_result to_chars(char* f, char* l, long long v, int b)      { return to_chars_signed_impl(f, l, v, b); }
to_chars_result to_chars(char* f, char* l, unsigned char v, int b)  { return to_chars_unsigned_impl(f, l, v, b); }
to_chars_result to_chars(char* f, char* l, unsigned short v, int b) { return to_chars_unsigned_impl(f, l, v, b); }
to_chars_result to_chars(char* f, char* l, unsigned int v, int b)   { return to_chars_unsigned_impl(f, l, v, b); }
to_chars_result to_chars(char* f, char* l, unsigned long v, int b)  { return to_chars_unsigned_impl(f, l, v, b); }
to_chars_result to_chars(char* f, char* l, unsigned long long v, int b) { return to_chars_unsigned_impl(f, l, v, b); }

// ---------------------------------------------------------------------------
// Integer from_chars
// ---------------------------------------------------------------------------

template <typename T>
static from_chars_result from_chars_unsigned_impl(
    const char* first, const char* last, T& value, int base)
{
    const char* p = first;
    if (p == last) return {first, errc::invalid_argument};

    // FIX: removed 0x/0X prefix acceptance for base 16

    int d = char_to_digit(*p, base);
    if (d < 0) return {first, errc::invalid_argument};

    using UT = unsigned long long;
    UT result = 0;
    UT max_val = static_cast<UT>(std::numeric_limits<T>::max());
    UT cutoff  = max_val / static_cast<UT>(base);
    // FIX: compute cutlim for precise overflow detection
    int cutlim = static_cast<int>(max_val % static_cast<UT>(base));

    bool overflow = false;
    while (p != last) {
        d = char_to_digit(*p, base);
        if (d < 0) break;

        // FIX: check both cutoff AND cutlim
        if (result > cutoff ||
            (result == cutoff && d > cutlim)) {
            overflow = true;
        }
        if (!overflow) {
            result = result * static_cast<UT>(base) + static_cast<UT>(d);
        }
        ++p;
    }

    if (p == first) return {first, errc::invalid_argument};
    if (overflow)   return {p, errc::result_out_of_range};
    if (result > max_val) return {p, errc::result_out_of_range};

    value = static_cast<T>(result);
    return {p, errc::ok};
}

template <typename T>
static from_chars_result from_chars_signed_impl(
    const char* first, const char* last, T& value, int base)
{
    if (first == last) return {first, errc::invalid_argument};

    bool negative = false;
    const char* p = first;

    if (*p == '-') {
        negative = true;
        ++p;
        if (p == last) return {first, errc::invalid_argument};
    }

    using UT = typename std::make_unsigned<T>::type;
    UT uval = 0;
    auto res = from_chars_unsigned_impl<UT>(p, last, uval, base);

    if (res.ec == errc::invalid_argument) {
        return {first, errc::invalid_argument};
    }
    if (res.ec == errc::result_out_of_range) {
        return res;
    }

    if (negative) {
        UT max_neg = static_cast<UT>(std::numeric_limits<T>::max()) + 1u;
        if (uval > max_neg) return {res.ptr, errc::result_out_of_range};
        if (uval == max_neg)
            value = std::numeric_limits<T>::min();
        else
            value = -static_cast<T>(uval);
    } else {
        if (uval > static_cast<UT>(std::numeric_limits<T>::max()))
            return {res.ptr, errc::result_out_of_range};
        value = static_cast<T>(uval);
    }
    return res;
}

// Explicit instantiations
from_chars_result from_chars(const char* f, const char* l, signed char& v, int b)    { return from_chars_signed_impl(f, l, v, b); }
from_chars_result from_chars(const char* f, const char* l, short& v, int b)          { return from_chars_signed_impl(f, l, v, b); }
from_chars_result from_chars(const char* f, const char* l, int& v, int b)            { return from_chars_signed_impl(f, l, v, b); }
from_chars_result from_chars(const char* f, const char* l, long& v, int b)           { return from_chars_signed_impl(f, l, v, b); }
from_chars_result from_chars(const char* f, const char* l, long long& v, int b)      { return from_chars_signed_impl(f, l, v, b); }
from_chars_result from_chars(const char* f, const char* l, unsigned char& v, int b)  { return from_chars_unsigned_impl(f, l, v, b); }
from_chars_result from_chars(const char* f, const char* l, unsigned short& v, int b) { return from_chars_unsigned_impl(f, l, v, b); }
from_chars_result from_chars(const char* f, const char* l, unsigned int& v, int b)   { return from_chars_unsigned_impl(f, l, v, b); }
from_chars_result from_chars(const char* f, const char* l, unsigned long& v, int b)  { return from_chars_unsigned_impl(f, l, v, b); }
from_chars_result from_chars(const char* f, const char* l, unsigned long long& v, int b) { return from_chars_unsigned_impl(f, l, v, b); }

// ---------------------------------------------------------------------------
// Float to_chars helpers — special value handling
// ---------------------------------------------------------------------------

static to_chars_result write_special(char* first, char* last, double value) {
    if (std::isnan(value)) {
        if (3 > last - first) return {last, errc::value_too_large};
        std::memcpy(first, "nan", 3);
        return {first + 3, errc::ok};
    }
    if (std::isinf(value)) {
        if (value < 0) {
            if (4 > last - first) return {last, errc::value_too_large};
            std::memcpy(first, "-inf", 4);
            return {first + 4, errc::ok};
        }
        if (3 > last - first) return {last, errc::value_too_large};
        std::memcpy(first, "inf", 3);
        return {first + 3, errc::ok};
    }
    if (value == 0.0) {
        if (std::signbit(value)) {
            if (2 > last - first) return {last, errc::value_too_large};
            std::memcpy(first, "-0", 2);
            return {first + 2, errc::ok};
        }
        if (1 > last - first) return {last, errc::value_too_large};
        *first = '0';
        return {first + 1, errc::ok};
    }
    // Not a special value
    return {nullptr, errc::ok};
}

// ---------------------------------------------------------------------------
// Float to_chars — shortest representation (double)
// ---------------------------------------------------------------------------

to_chars_result to_chars(char* first, char* last, double value) {
    auto sp = write_special(first, last, value);
    if (sp.ptr != nullptr) return sp;

    // Find shortest %.*g representation that round-trips
    char buf[32];
    int best_len = 0;

    for (int n = 1; n <= 17; ++n) {
        best_len = std::snprintf(buf, sizeof(buf), "%.*g", n, value);
        char* endp;
        double check = std::strtod(buf, &endp);
        if (check == value) break;
    }

    if (best_len <= 0) {
        best_len = std::snprintf(buf, sizeof(buf), "%.17g", value);
    }

    if (best_len > static_cast<int>(last - first)) {
        return {last, errc::value_too_large};
    }

    std::memcpy(first, buf, static_cast<size_t>(best_len));
    return {first + best_len, errc::ok};
}

// ---------------------------------------------------------------------------
// Float to_chars — shortest representation (float)
// ---------------------------------------------------------------------------

to_chars_result to_chars(char* first, char* last, float value) {
    // Handle special values
    if (std::isnan(value)) {
        if (3 > last - first) return {last, errc::value_too_large};
        std::memcpy(first, "nan", 3);
        return {first + 3, errc::ok};
    }
    if (std::isinf(value)) {
        if (value < 0) {
            if (4 > last - first) return {last, errc::value_too_large};
            std::memcpy(first, "-inf", 4);
            return {first + 4, errc::ok};
        }
        if (3 > last - first) return {last, errc::value_too_large};
        std::memcpy(first, "inf", 3);
        return {first + 3, errc::ok};
    }
    if (value == 0.0f) {
        if (std::signbit(value)) {
            if (2 > last - first) return {last, errc::value_too_large};
            std::memcpy(first, "-0", 2);
            return {first + 2, errc::ok};
        }
        if (1 > last - first) return {last, errc::value_too_large};
        *first = '0';
        return {first + 1, errc::ok};
    }

    // FIX: float-specific shortest using strtof for round-trip check
    char buf[32];
    int best_len = 0;
    for (int n = 1; n <= 9; ++n) {
        best_len = std::snprintf(buf, sizeof(buf), "%.*g", n, static_cast<double>(value));
        char* endp;
        float check = std::strtof(buf, &endp);
        if (check == value) break;
    }
    if (best_len <= 0) {
        best_len = std::snprintf(buf, sizeof(buf), "%.9g", static_cast<double>(value));
    }
    if (best_len > static_cast<int>(last - first)) {
        return {last, errc::value_too_large};
    }
    std::memcpy(first, buf, static_cast<size_t>(best_len));
    return {first + best_len, errc::ok};
}

// ---------------------------------------------------------------------------
// Float to_chars — with chars_format (shortest for given format)
// ---------------------------------------------------------------------------

to_chars_result to_chars(char* first, char* last, double value, chars_format fmt) {
    auto sp = write_special(first, last, value);
    if (sp.ptr != nullptr) return sp;

    char buf[512];
    int best_len = 0;

    if (fmt == chars_format::scientific) {
        for (int p = 0; p <= 17; ++p) {
            best_len = std::snprintf(buf, sizeof(buf), "%.*e", p, value);
            double check = std::strtod(buf, nullptr);
            if (check == value) break;
        }
    } else if (fmt == chars_format::fixed) {
        for (int p = 0; p <= 350; ++p) {
            best_len = std::snprintf(buf, sizeof(buf), "%.*f", p, value);
            double check = std::strtod(buf, nullptr);
            if (check == value) break;
        }
    } else if (fmt == chars_format::hex) {
        char hbuf[128];
        for (int p = 0; p <= 13; ++p) {
            int n = std::snprintf(hbuf, sizeof(hbuf), "%.*a", p, value);
            double check = std::strtod(hbuf, nullptr);
            if (check == value) {
                // Strip "0x" or "-0x" prefix
                if (hbuf[0] == '-') {
                    buf[0] = '-';
                    std::memcpy(buf + 1, hbuf + 3, static_cast<std::size_t>(n - 3));
                    best_len = n - 2;
                } else {
                    std::memcpy(buf, hbuf + 2, static_cast<std::size_t>(n - 2));
                    best_len = n - 2;
                }
                break;
            }
        }
    } else { // general
        for (int n = 1; n <= 17; ++n) {
            best_len = std::snprintf(buf, sizeof(buf), "%.*g", n, value);
            double check = std::strtod(buf, nullptr);
            if (check == value) break;
        }
    }

    if (best_len <= 0) {
        best_len = std::snprintf(buf, sizeof(buf), "%.17g", value);
    }

    if (best_len > static_cast<int>(last - first)) {
        return {last, errc::value_too_large};
    }

    std::memcpy(first, buf, static_cast<size_t>(best_len));
    return {first + best_len, errc::ok};
}

// ---------------------------------------------------------------------------
// Float to_chars — with chars_format and precision
// ---------------------------------------------------------------------------

to_chars_result to_chars(char* first, char* last, double value, chars_format fmt, int precision) {
    auto sp = write_special(first, last, value);
    if (sp.ptr != nullptr) return sp;

    char buf[512];
    int n = 0;

    if (fmt == chars_format::scientific) {
        n = std::snprintf(buf, sizeof(buf), "%.*e", precision, value);
    } else if (fmt == chars_format::fixed) {
        n = std::snprintf(buf, sizeof(buf), "%.*f", precision, value);
    } else if (fmt == chars_format::hex) {
        // FIX: use %a and strip "0x" prefix
        char hbuf[128];
        int hn = std::snprintf(hbuf, sizeof(hbuf), "%.*a", precision, value);
        if (hbuf[0] == '-') {
            buf[0] = '-';
            std::memcpy(buf + 1, hbuf + 3, static_cast<std::size_t>(hn - 3));
            n = hn - 2;
        } else {
            std::memcpy(buf, hbuf + 2, static_cast<std::size_t>(hn - 2));
            n = hn - 2;
        }
    } else { // general
        n = std::snprintf(buf, sizeof(buf), "%.*g", precision, value);
    }

    if (n <= 0 || n > static_cast<int>(last - first)) {
        return {last, errc::value_too_large};
    }

    std::memcpy(first, buf, static_cast<size_t>(n));
    return {first + n, errc::ok};
}

// ---------------------------------------------------------------------------
// Float from_chars — spec-compliant parsing with chars_format
// ---------------------------------------------------------------------------

from_chars_result from_chars(const char* first, const char* last, double& value, chars_format fmt) {
    if (first == last) return {first, errc::invalid_argument};

    const char* p = first;

    // Only '-' sign allowed (no '+')
    bool negative = false;
    if (*p == '-') {
        negative = true;
        ++p;
    } else if (*p == '+') {
        return {first, errc::invalid_argument};
    }

    if (p == last) return {first, errc::invalid_argument};

    // Reject leading whitespace
    if (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r' ||
        *p == '\v' || *p == '\f') {
        return {first, errc::invalid_argument};
    }

    // Check for nan/inf (case-insensitive)
    auto remaining = last - p;
    if (remaining >= 3) {
        if ((p[0] == 'n' || p[0] == 'N') &&
            (p[1] == 'a' || p[1] == 'A') &&
            (p[2] == 'n' || p[2] == 'N')) {
            value = negative
                ? -std::numeric_limits<double>::quiet_NaN()
                :  std::numeric_limits<double>::quiet_NaN();
            return {p + 3, errc::ok};
        }
        if ((p[0] == 'i' || p[0] == 'I') &&
            (p[1] == 'n' || p[1] == 'N') &&
            (p[2] == 'f' || p[2] == 'F')) {
            value = negative
                ? -std::numeric_limits<double>::infinity()
                :  std::numeric_limits<double>::infinity();
            return {p + 3, errc::ok};
        }
    }

    // ---------------------------------------------------------------
    // Hex float format
    // ---------------------------------------------------------------
    if (fmt == chars_format::hex) {
        const char* match_start = p;
        bool has_digit = false;

        // Parse hex significand digits
        while (p != last && is_hex_digit(*p)) {
            has_digit = true;
            ++p;
        }

        // Fractional part
        if (p != last && *p == '.') {
            ++p;
            while (p != last && is_hex_digit(*p)) {
                has_digit = true;
                ++p;
            }
        }

        if (!has_digit) return {first, errc::invalid_argument};

        // Binary exponent: p/P followed by optional sign and decimal digits
        if (p != last && (*p == 'p' || *p == 'P')) {
            const char* exp_mark = p;
            ++p;
            if (p != last && (*p == '+' || *p == '-')) ++p;
            if (p == last || !(*p >= '0' && *p <= '9')) {
                p = exp_mark; // backtrack — no valid exponent
            } else {
                while (p != last && *p >= '0' && *p <= '9') ++p;
            }
        }

        // Copy with "0x" prefix for strtod
        std::size_t match_len = static_cast<std::size_t>(p - match_start);
        char buf[520];
        if (match_len + 3 >= sizeof(buf)) {
            return {first, errc::invalid_argument};
        }
        buf[0] = '0';
        buf[1] = 'x';
        std::memcpy(buf + 2, match_start, match_len);
        buf[match_len + 2] = '\0';

        errno = 0;
        char* endp = nullptr;
        double result = std::strtod(buf, &endp);

        if (endp != buf + match_len + 2) {
            return {first, errc::invalid_argument};
        }

        if (errno == ERANGE && std::isinf(result)) {
            return {p, errc::result_out_of_range};
        }

        value = negative ? -result : result;
        return {p, errc::ok};
    }

    // ---------------------------------------------------------------
    // Decimal float formats (scientific, fixed, general)
    // ---------------------------------------------------------------

    // Must start with a digit or '.'
    if (!((*p >= '0' && *p <= '9') || *p == '.')) {
        return {first, errc::invalid_argument};
    }

    const char* match_start = p;
    bool has_digit = false;

    // Integer part
    while (p != last && *p >= '0' && *p <= '9') {
        has_digit = true;
        ++p;
    }

    // Fractional part
    if (p != last && *p == '.') {
        ++p;
        while (p != last && *p >= '0' && *p <= '9') {
            has_digit = true;
            ++p;
        }
    }

    if (!has_digit) return {first, errc::invalid_argument};

    // Exponent part — parse only if format allows it
    bool has_exponent = false;
    if (fmt != chars_format::fixed) {
        if (p != last && (*p == 'e' || *p == 'E')) {
            const char* exp_mark = p;
            ++p;
            if (p != last && (*p == '+' || *p == '-')) ++p;
            if (p == last || !(*p >= '0' && *p <= '9')) {
                p = exp_mark; // backtrack — invalid exponent
            } else {
                has_exponent = true;
                while (p != last && *p >= '0' && *p <= '9') ++p;
            }
        }
    }

    // Scientific requires exponent
    if (fmt == chars_format::scientific && !has_exponent) {
        return {first, errc::invalid_argument};
    }

    // Copy matched portion to null-terminated buffer for strtod
    std::size_t match_len = static_cast<std::size_t>(p - match_start);
    char buf[512];
    if (match_len >= sizeof(buf)) {
        return {first, errc::invalid_argument};
    }
    std::memcpy(buf, match_start, match_len);
    buf[match_len] = '\0';

    // Parse with strtod (C locale)
    errno = 0;
    char* endp = nullptr;
    double result = std::strtod(buf, &endp);

    if (endp != buf + match_len) {
        return {first, errc::invalid_argument};
    }

    // Check for overflow
    if (errno == ERANGE && std::isinf(result)) {
        return {p, errc::result_out_of_range};
    }
    // Underflow to subnormal/zero is not an error

    value = negative ? -result : result;
    return {p, errc::ok};
}

// ---------------------------------------------------------------------------
// Float from_chars — float type with overflow detection
// ---------------------------------------------------------------------------

from_chars_result from_chars(const char* first, const char* last, float& value, chars_format fmt) {
    double dval;
    auto res = from_chars(first, last, dval, fmt);
    if (res.ec == errc::ok) {
        // FIX: detect float overflow
        if (std::isinf(static_cast<float>(dval)) && !std::isinf(dval)) {
            return {res.ptr, errc::result_out_of_range};
        }
        value = static_cast<float>(dval);
    }
    return res;
}

} // namespace myconv
