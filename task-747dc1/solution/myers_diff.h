#pragma once

#include <string>
#include <vector>

namespace fredbuf {

struct DiffHunk {
    enum Op { Insert, Delete, Equal };
    Op op;
    std::string line;
    int old_lineno;
    int new_lineno;
};

std::vector<DiffHunk> myers_diff(const std::string& old_text, const std::string& new_text);

} // namespace fredbuf
