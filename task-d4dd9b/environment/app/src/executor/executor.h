#pragma once
#include <dataflow/core.h>
#include <dataflow/compress.h>

class Executor {
public:
    dataflow::DataFrame run(const dataflow::DataFrame& input);
};
