#include "parser.h"
#include "generated_rules.h"
#include <dataflow/core.h>
#include <sstream>

Parser::Parser() {
    pipeline_.add_stage([](const dataflow::DataFrame& df) {
        dataflow::DataFrame result = df;
        for (auto& v : result.values) {
            v *= GENERATED_SCALE_FACTOR;
        }
        return result;
    });
}

dataflow::DataFrame Parser::parse(const std::string& input) {
    dataflow::DataFrame df;
    df.name = "parsed";
    std::istringstream iss(input);
    double val;
    while (iss >> val) {
        df.values.push_back(val);
    }
    return pipeline_.execute(df);
}
