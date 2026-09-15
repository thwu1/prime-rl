#include <dataflow/v2/pipeline.h>

namespace dataflow {

void Pipeline::add_stage(std::function<DataFrame(const DataFrame&)> stage) {
    stages_.push_back(std::move(stage));
}

DataFrame Pipeline::execute(const DataFrame& input) const {
    DataFrame current = input;
    for (const auto& stage : stages_) {
        current = stage(current);
    }
    return current;
}

} // namespace dataflow
