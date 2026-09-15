#pragma once
#include <dataflow/pipeline.h>
#include <string>

class Parser {
public:
    Parser();
    dataflow::DataFrame parse(const std::string& input);
private:
    dataflow::Pipeline pipeline_;
};
