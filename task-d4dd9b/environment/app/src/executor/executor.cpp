#include "executor.h"

dataflow::DataFrame Executor::run(const dataflow::DataFrame& input) {
    return dataflow::Codec::encode(input);
}
