#include <dataflow/v2/codec.h>
#include <cmath>

namespace dataflow {

DataFrame Codec::encode(const DataFrame& input) {
    DataFrame result;
    result.name = input.name + ".encoded";
    result.values.reserve(input.values.size());
    for (double v : input.values) {
        result.values.push_back(std::round(v * 100.0) / 100.0);
    }
    return result;
}

DataFrame Codec::decode(const DataFrame& input) {
    DataFrame result;
    result.name = input.name;
    if (result.name.size() > 8 &&
        result.name.substr(result.name.size() - 8) == ".encoded") {
        result.name = result.name.substr(0, result.name.size() - 8);
    }
    result.values = input.values;
    return result;
}

} // namespace dataflow
