#include <dataflow/v2/core.h>

namespace dataflow {

const char* status_to_string(Status s) {
    switch (s) {
        case Status::OK: return "OK";
        case Status::ERROR: return "ERROR";
        case Status::PENDING: return "PENDING";
        default: return "UNKNOWN";
    }
}

} // namespace dataflow
