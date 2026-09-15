#ifndef MYCHARCONV_HPP
#define MYCHARCONV_HPP


namespace myconv {

enum class errc {
    ok = 0,
    invalid_argument = 1,
    result_out_of_range = 2,
    value_too_large = 3
};

enum class chars_format {
    scientific = 1,
    fixed      = 2,
    hex        = 4,
    general    = 3   // scientific | fixed
};

struct to_chars_result {
    char* ptr;
    errc ec;
};

struct from_chars_result {
    const char* ptr;
    errc ec;
};

// Integer to_chars
to_chars_result to_chars(char* first, char* last, signed char value, int base = 10);
to_chars_result to_chars(char* first, char* last, short value, int base = 10);
to_chars_result to_chars(char* first, char* last, int value, int base = 10);
to_chars_result to_chars(char* first, char* last, long value, int base = 10);
to_chars_result to_chars(char* first, char* last, long long value, int base = 10);
to_chars_result to_chars(char* first, char* last, unsigned char value, int base = 10);
to_chars_result to_chars(char* first, char* last, unsigned short value, int base = 10);
to_chars_result to_chars(char* first, char* last, unsigned int value, int base = 10);
to_chars_result to_chars(char* first, char* last, unsigned long value, int base = 10);
to_chars_result to_chars(char* first, char* last, unsigned long long value, int base = 10);

// Integer from_chars
from_chars_result from_chars(const char* first, const char* last, signed char& value, int base = 10);
from_chars_result from_chars(const char* first, const char* last, short& value, int base = 10);
from_chars_result from_chars(const char* first, const char* last, int& value, int base = 10);
from_chars_result from_chars(const char* first, const char* last, long& value, int base = 10);
from_chars_result from_chars(const char* first, const char* last, long long& value, int base = 10);
from_chars_result from_chars(const char* first, const char* last, unsigned char& value, int base = 10);
from_chars_result from_chars(const char* first, const char* last, unsigned short& value, int base = 10);
from_chars_result from_chars(const char* first, const char* last, unsigned int& value, int base = 10);
from_chars_result from_chars(const char* first, const char* last, unsigned long& value, int base = 10);
from_chars_result from_chars(const char* first, const char* last, unsigned long long& value, int base = 10);

// Floating-point to_chars — shortest representation with round-trip guarantee
to_chars_result to_chars(char* first, char* last, float value);
to_chars_result to_chars(char* first, char* last, double value);

// Floating-point to_chars — formatted output
to_chars_result to_chars(char* first, char* last, double value, chars_format fmt);
to_chars_result to_chars(char* first, char* last, double value, chars_format fmt, int precision);

// Floating-point from_chars
from_chars_result from_chars(const char* first, const char* last, float& value,
                             chars_format fmt = chars_format::general);
from_chars_result from_chars(const char* first, const char* last, double& value,
                             chars_format fmt = chars_format::general);

} // namespace myconv

#endif // MYCHARCONV_HPP
