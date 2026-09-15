
#include "charconv.hpp"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include <cerrno>
#include <limits>
#include <type_traits>

namespace myconv {

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static char digit_to_char(int d) {
    if (d < 10) return static_cast<char>('0' + d);
    return static_cast<char>('A' + (d - 10));
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

// ---------------------------------------------------------------------------
// Integer to_chars
// ---------------------------------------------------------------------------

template <typename T>
static to_chars_result to_chars_unsigned_impl(char* first, char* last, T value, int base) {
    char buf[65]; // enough for 64-bit binary
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

    // Reverse digits into output buffer
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

    // Negative value: write '-' then the magnitude
    if (first >= last) return {last, errc::value_too_large};
    *first++ = '-';

    if (value == std::numeric_limits<T>::min()) {
        return to_chars_unsigned_impl<UT>(
            first, last,
            static_cast<UT>(std::numeric_limits<T>::max()), base);
    }
    return to_chars_unsigned_impl<UT>(first, last, static_cast<UT>(-value), base);
}

// Explicit instantiations — integer to_chars
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

    if (base == 16 && (last - p) >= 2 && *p == '0'
        && (*(p + 1) == 'x' || *(p + 1) == 'X')) {
        p += 2;
    }

    if (p == last) return {first, errc::invalid_argument};

    int d = char_to_digit(*p, base);
    if (d < 0) return {first, errc::invalid_argument};

    using UT = unsigned long long;
    UT result = 0;
    UT max_val = static_cast<UT>(std::numeric_limits<T>::max());
    UT cutoff  = max_val / static_cast<UT>(base);

    bool overflow = false;
    while (p != last) {
        d = char_to_digit(*p, base);
        if (d < 0) break;

        if (result > cutoff) {
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

// Explicit instantiations — integer from_chars
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
// Float to_chars
// ---------------------------------------------------------------------------

to_chars_result to_chars(char* first, char* last, double value) {
    char buf[32];
    int n = std::snprintf(buf, sizeof(buf), "%.17g", value);

    if (n <= 0 || n > static_cast<int>(last - first)) {
        return {last, errc::value_too_large};
    }

    std::memcpy(first, buf, static_cast<size_t>(n));
    return {first + n, errc::ok};
}

to_chars_result to_chars(char* first, char* last, float value) {
    return to_chars(first, last, static_cast<double>(value));
}

to_chars_result to_chars(char* first, char* last, double value, chars_format fmt) {
    (void)fmt;
    return to_chars(first, last, value);
}

to_chars_result to_chars(char* first, char* last, double value, chars_format fmt, int precision) {
    char buf[512];
    int n;
    if (fmt == chars_format::scientific) {
        n = std::snprintf(buf, sizeof(buf), "%.*e", precision, value);
    } else if (fmt == chars_format::fixed) {
        n = std::snprintf(buf, sizeof(buf), "%.*f", precision, value);
    } else if (fmt == chars_format::hex) {
        n = std::snprintf(buf, sizeof(buf), "%.*g", precision, value);
    } else {
        n = std::snprintf(buf, sizeof(buf), "%.17g", value);
    }
    if (n <= 0 || n > static_cast<int>(last - first)) {
        return {last, errc::value_too_large};
    }
    std::memcpy(first, buf, static_cast<size_t>(n));
    return {first + n, errc::ok};
}

// ---------------------------------------------------------------------------
// Float from_chars
// ---------------------------------------------------------------------------

from_chars_result from_chars(const char* first, const char* last, double& value, chars_format fmt) {
    if (first == last) return {first, errc::invalid_argument};

    (void)fmt;
    char* end = nullptr;
    double result = std::strtod(first, &end);

    if (end == first) return {first, errc::invalid_argument};

    value = result;
    return {end, errc::ok};
}

from_chars_result from_chars(const char* first, const char* last, float& value, chars_format fmt) {
    double dval;
    auto res = from_chars(first, last, dval, fmt);
    if (res.ec == errc::ok) {
        value = static_cast<float>(dval);
    }
    return res;
}

} // namespace myconv
