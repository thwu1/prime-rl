#pragma once
#include <dataflow/v2/core.h>
#include <functional>
#include <vector>

namespace dataflow {

class Pipeline {
public:
    Pipeline() = default;
    void add_stage(std::function<DataFrame(const DataFrame&)> stage);
    DataFrame execute(const DataFrame& input) const;
private:
    std::vector<std::function<DataFrame(const DataFrame&)>> stages_;
};

} // namespace dataflow
