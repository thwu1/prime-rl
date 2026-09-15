#include <iostream>
#include <fstream>
#include <string>
#include <cmath>
#include <cfloat>
#include <vector>
#include <algorithm>
#include <iomanip>
#include <numeric>
#include <map>
#include "simdjson.h"


using namespace simdjson;

struct GroupStats {
    size_t count = 0;
    double sum = 0.0;
    double min_val = 0.0;
    double max_val = -DBL_MAX;
    std::vector<double> values;
};

std::string detect_format(const char* data, size_t len) {
    size_t i = 0;
    while (i < len && (data[i] == ' ' || data[i] == '\t' ||
                       data[i] == '\n' || data[i] == '\r')) {
        i++;
    }
    if (i >= len) return "ndjson";
    if (data[i] == '[') {
        return "rfc7464";
    }
    return "ndjson";
}

std::string strip_rs_delimiters(const std::string& input) {
    std::string out;
    out.reserve(input.size());
    for (size_t i = 0; i < input.size(); i++) {
        if (static_cast<unsigned char>(input[i]) == 0x1E) {
            out.push_back('\n');
        } else {
            out.push_back(input[i]);
        }
    }
    return out;
}

double compute_percentile(std::vector<double>& vals, double pct) {
    if (vals.empty()) return 0.0;
    size_t n = vals.size();
    double rank = (pct / 100.0) * static_cast<double>(n);
    size_t idx = static_cast<size_t>(rank);
    if (idx >= n) idx = n - 1;
    return vals[idx];
}

double compute_aggregation(const std::string& agg, GroupStats& gs,
                           size_t total_docs) {
    if (agg == "count") return static_cast<double>(gs.count);
    if (agg == "sum")   return gs.sum;
    if (agg == "min")   return gs.count > 0 ? gs.min_val : 0.0;
    if (agg == "max")   return gs.count > 0 ? gs.max_val : 0.0;

    if (agg == "avg") {
        return total_docs > 0
               ? gs.sum / static_cast<double>(total_docs)
               : 0.0;
    }

    if (agg == "median") {
        if (gs.values.empty()) return 0.0;
        size_t n = gs.values.size();
        return gs.values[n / 2];
    }

    if (agg == "stddev") {
        if (gs.values.empty()) return 0.0;
        double mean = gs.sum / static_cast<double>(total_docs);
        double sq_sum = 0.0;
        for (double v : gs.values) {
            sq_sum += (v - mean) * (v - mean);
        }
        size_t n = gs.values.size();
        return std::sqrt(sq_sum / static_cast<double>(n - 1));
    }

    if (agg.rfind("percentile", 0) == 0) {
        size_t colon = agg.find(':');
        if (colon == std::string::npos) return 0.0;
        double pct = std::stod(agg.substr(colon + 1));
        return compute_percentile(gs.values, pct);
    }

    if (agg == "values") return static_cast<double>(gs.values.size());

    std::cerr << "Error: unknown aggregation '" << agg << "'\n";
    return 0.0;
}

int main(int argc, char* argv[]) {
    if (argc < 5) {
        std::cerr << "Usage: " << argv[0]
                  << " <file> <format> <pointer> <agg> [--group-by <pointer>]\n"
                  << "Formats: auto, ndjson, rfc7464\n"
                  << "Aggregations: count, sum, min, max, avg, median, stddev, "
                  << "percentile:N, values\n";
        return 1;
    }

    const std::string file_path = argv[1];
    const std::string fmt_arg   = argv[2];
    const std::string pointer   = argv[3];
    const std::string agg       = argv[4];

    std::string group_by_pointer;
    bool use_group_by = false;
    for (int i = 5; i < argc - 1; i++) {
        if (std::string(argv[i]) == "--group-by") {
            group_by_pointer = argv[i + 1];
            use_group_by = true;
        }
    }

    std::ifstream ifs(file_path, std::ios::binary);
    if (!ifs) {
        std::cerr << "Error: cannot open " << file_path << "\n";
        return 1;
    }
    std::string raw((std::istreambuf_iterator<char>(ifs)),
                     std::istreambuf_iterator<char>());
    ifs.close();
    if (raw.empty()) {
        std::cerr << "Error: empty input\n";
        return 1;
    }

    std::string format;
    if (fmt_arg == "auto") {
        format = detect_format(raw.data(), raw.size());
    } else {
        format = fmt_arg;
    }

    std::string processed;
    if (format == "rfc7464") {
        processed = strip_rs_delimiters(raw);
    } else {
        processed = raw;
    }

    constexpr size_t BATCH_SIZE = 256;

    padded_string ps(raw);
    ondemand::parser parser;
    ondemand::document_stream ds;

    auto err = parser.iterate_many(ps, BATCH_SIZE).get(ds);
    if (err) {
        std::cerr << "Error: stream init failed: " << err << "\n";
        return 1;
    }

    size_t total_documents = 0;
    size_t valid_documents = 0;
    size_t error_documents = 0;

    GroupStats global;
    std::map<std::string, GroupStats> groups;

    std::string field = pointer;
    if (!field.empty() && field[0] == '/')
        field = field.substr(1);

    for (auto doc : ds) {
        total_documents++;

        double v;
        auto val_err = doc[field].get_double().get(v);
        if (val_err) {
            continue;
        }
        valid_documents++;

        global.count++;
        global.sum += v;
        if (v < global.min_val) global.min_val = v;
        if (v > global.max_val) global.max_val = v;
        global.values.push_back(v);

        if (use_group_by) {
            std::string_view gk_sv;
            auto gk_err = doc.at_pointer(group_by_pointer).get_string().get(gk_sv);
            if (!gk_err) {
                std::string gk(gk_sv);
                GroupStats fresh;
                fresh.count = 1;
                fresh.sum = v;
                fresh.min_val = v;
                fresh.max_val = v;
                fresh.values.push_back(v);
                groups[gk] = fresh;
            }
        }
    }

    size_t truncated_bytes = 0;
    error_documents = total_documents - valid_documents;

    double result = compute_aggregation(agg, global, total_documents);

    std::cout << std::setprecision(17)
              << "{\n"
              << "  \"total_documents\": " << total_documents << ",\n"
              << "  \"valid_documents\": " << valid_documents << ",\n"
              << "  \"error_documents\": " << error_documents << ",\n"
              << "  \"truncated_bytes\": " << truncated_bytes << ",\n"
              << "  \"detected_format\": \"" << format << "\",\n";

    if (use_group_by) {
        std::cout << "  \"groups\": {\n";
        size_t gi = 0;
        for (auto& [key, gs] : groups) {
            double grp_result = compute_aggregation(agg, gs, total_documents);
            std::cout << "    \"" << key << "\": {"
                      << "\"count\": " << gs.count << ", "
                      << "\"sum\": " << gs.sum << ", "
                      << "\"result\": " << grp_result
                      << "}";
            if (gi < groups.size() - 1) std::cout << ",";
            std::cout << "\n";
            gi++;
        }
        std::cout << "  },\n";
    }

    if (agg == "values") {
        std::cout << "  \"values\": [";
        for (size_t i = 0; i < global.values.size(); i++) {
            if (i) std::cout << ", ";
            std::cout << global.values[i];
        }
        std::cout << "],\n";
    }
    std::cout << "  \"result\": " << result << "\n"
              << "}\n";

    return 0;
}
