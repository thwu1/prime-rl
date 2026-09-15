#pragma once
#include <dataflow/v2/core.h>

namespace dataflow {

class Codec {
public:
    static DataFrame encode(const DataFrame& input);
    static DataFrame decode(const DataFrame& input);
};

} // namespace dataflow
