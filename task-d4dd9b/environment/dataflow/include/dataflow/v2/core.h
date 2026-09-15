#pragma once
#include <string>
#include <vector>

namespace dataflow {

struct DataFrame {
    std::string name;
    std::vector<double> values;
    size_t rows() const { return values.size(); }
};

enum class Status { OK, ERROR, PENDING };

const char* status_to_string(Status s);

} // namespace dataflow
