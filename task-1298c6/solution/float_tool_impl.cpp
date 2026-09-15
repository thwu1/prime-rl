
#include <iostream>
#include <string>
#include <charconv>
#include <cstring>
#include <cstdint>
#include <cinttypes>

int main() {
    std::string line;
    while (std::getline(std::cin, line)) {
        // Trim whitespace
        auto start = line.find_first_not_of(" \t\r\n");
        if (start == std::string::npos) continue;
        auto end = line.find_last_not_of(" \t\r\n");
        std::string s = line.substr(start, end - start + 1);
        if (s.empty()) continue;

        double value = 0.0;
        auto result = std::from_chars(s.data(), s.data() + s.size(), value);
        if (result.ec != std::errc{}) {
            // from_chars may not handle inf/nan on all impls; skip failures
            continue;
        }

        uint64_t bits;
        std::memcpy(&bits, &value, sizeof(bits));
        std::printf("%016" PRIx64 "\n", bits);
    }
    return 0;
}
