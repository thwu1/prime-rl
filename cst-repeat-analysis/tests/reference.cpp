// Reference CST analyzer for test verification.
// Identical logic to the solution, writes to /tests/expected.json by default.
//

#include <sdsl/suffix_trees.hpp>
#include <sdsl/suffix_array_algorithm.hpp>

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

using namespace sdsl;
using namespace std;

static string json_escape(const string& s) {
    string r;
    r.reserve(s.size());
    for (char c : s) {
        switch (c) {
            case '"':  r += "\\\""; break;
            case '\\': r += "\\\\"; break;
            case '\n': r += "\\n"; break;
            case '\r': r += "\\r"; break;
            case '\t': r += "\\t"; break;
            default:
                if (static_cast<unsigned char>(c) < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x",
                             static_cast<unsigned char>(c));
                    r += buf;
                } else {
                    r += c;
                }
        }
    }
    return r;
}

int main() {
    string outfile = "/tests/expected.json";

    string text;
    {
        ifstream f("/app/corpus.txt");
        if (!f) { cerr << "Cannot open /app/corpus.txt\n"; return 1; }
        text.assign(istreambuf_iterator<char>(f), istreambuf_iterator<char>());
    }

    vector<string> queries;
    {
        ifstream f("/app/queries.txt");
        if (!f) { cerr << "Cannot open /app/queries.txt\n"; return 1; }
        string line;
        while (getline(f, line)) {
            while (!line.empty() && (line.back() == '\r' || line.back() == '\n'))
                line.pop_back();
            if (!line.empty()) queries.push_back(line);
        }
    }

    using cst_t = cst_sct3<>;
    using node_t = cst_t::node_type;
    cst_t cst;
    construct_im(cst, text, 1);

    uint64_t n_internal = 0, n_leaves = 0;
    uint64_t max_depth = 0, lrs_lb = 0, lrs_freq = 0;
    uint64_t n_maximal = 0, n_supermaximal = 0;

    vector<node_t> stk;
    stk.reserve(1024);
    stk.push_back(cst.root());

    while (!stk.empty()) {
        node_t v = stk.back();
        stk.pop_back();

        if (cst.is_leaf(v)) {
            n_leaves++;
            continue;
        }

        n_internal++;
        uint64_t d  = cst.depth(v);
        uint64_t lb = cst.lb(v);
        uint64_t rb = cst.rb(v);
        uint64_t freq = rb - lb + 1;

        uint64_t deg = cst.degree(v);
        vector<node_t> children;
        children.reserve(deg);
        bool all_children_leaves = true;
        for (uint64_t i = 1; i <= deg; i++) {
            node_t ch = cst.select_child(v, i);
            children.push_back(ch);
            if (!cst.is_leaf(ch)) all_children_leaves = false;
        }

        for (int64_t i = static_cast<int64_t>(children.size()) - 1; i >= 0; i--) {
            stk.push_back(children[i]);
        }

        if (d == 0) continue;

        if (d > max_depth || (d == max_depth && lb < lrs_lb)) {
            max_depth = d;
            lrs_lb   = lb;
            lrs_freq = freq;
        }

        bool left_diverse = false;
        {
            auto first_bwt = cst.csa.bwt[lb];
            for (uint64_t i = lb + 1; i <= rb; i++) {
                if (cst.csa.bwt[i] != first_bwt) {
                    left_diverse = true;
                    break;
                }
            }
        }

        if (left_diverse) {
            n_maximal++;
            if (all_children_leaves) n_supermaximal++;
        }
    }

    string lrs;
    if (max_depth > 0) {
        uint64_t sa_pos = cst.csa[lrs_lb];
        lrs = sdsl::extract(cst.csa, sa_pos, sa_pos + max_depth - 1);
    }

    vector<pair<string, uint64_t>> pcounts;
    pcounts.reserve(queries.size());
    for (const auto& q : queries) {
        uint64_t cnt = sdsl::count(cst.csa, q.begin(), q.end());
        pcounts.push_back({q, cnt});
    }

    uint64_t space = size_in_bytes(cst);

    ofstream out(outfile);
    if (!out) { cerr << "Cannot write " << outfile << "\n"; return 1; }

    out << "{\n";
    out << "  \"num_internal_nodes\": " << n_internal << ",\n";
    out << "  \"num_leaves\": "         << n_leaves   << ",\n";
    out << "  \"longest_repeat_length\": "    << max_depth << ",\n";
    out << "  \"longest_repeat_string\": \""  << json_escape(lrs) << "\",\n";
    out << "  \"longest_repeat_frequency\": " << lrs_freq << ",\n";
    out << "  \"num_maximal_repeats\": "      << n_maximal << ",\n";
    out << "  \"num_supermaximal_repeats\": "  << n_supermaximal << ",\n";
    out << "  \"space_bytes\": "              << space << ",\n";
    out << "  \"pattern_counts\": {";
    for (size_t i = 0; i < pcounts.size(); i++) {
        if (i > 0) out << ",";
        out << "\n    \"" << json_escape(pcounts[i].first) << "\": "
            << pcounts[i].second;
    }
    out << "\n  }\n}\n";
    out.close();

    cerr << "Reference results written to " << outfile << endl;
    return 0;
}
