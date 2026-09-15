#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#include <sdsl/suffix_arrays.hpp>
#include <sdsl/wavelet_trees.hpp>

using namespace sdsl;

int main()
{
    // === Index integer sequence ===

    std::vector<uint64_t> raw_seq;
    {
        std::ifstream f("/app/sequence.txt");
        uint64_t val;
        while (f >> val)
            raw_seq.push_back(val);
    }

    int_vector<> iv(raw_seq.size());
    for (size_t i = 0; i < raw_seq.size(); i++)
        iv[i] = raw_seq[i];
    util::bit_compress(iv);

    wt_int<> wt;
    construct_im(wt, iv);

    // Process wavelet tree queries
    std::vector<int64_t> wt_results;
    {
        std::ifstream qf("/app/wt_queries.txt");
        std::string line;
        while (std::getline(qf, line))
        {
            if (line.empty())
                continue;
            std::istringstream iss(line);
            std::string type;
            iss >> type;

            if (type == "ACCESS")
            {
                uint64_t pos;
                iss >> pos;
                wt_results.push_back(static_cast<int64_t>(wt[pos]));
            }
            else if (type == "RANK")
            {
                uint64_t pos, val;
                iss >> pos >> val;
                wt_results.push_back(static_cast<int64_t>(wt.rank(pos, val)));
            }
            else if (type == "SELECT")
            {
                uint64_t i_arg, val;
                iss >> i_arg >> val;
                wt_results.push_back(static_cast<int64_t>(wt.select(i_arg, val)));
            }
            else if (type == "COUNT")
            {
                uint64_t lb, rb, val;
                iss >> lb >> rb >> val;
                int64_t cnt = static_cast<int64_t>(wt.rank(rb, val))
                            - static_cast<int64_t>(wt.rank(lb, val));
                wt_results.push_back(cnt);
            }
            else if (type == "RANGE")
            {
                uint64_t lb, rb, lo, hi;
                iss >> lb >> rb >> lo >> hi;
                if (rb > lb)
                {
                    auto res = wt.range_search_2d(lb, rb - 1, lo, hi);
                    wt_results.push_back(static_cast<int64_t>(res.first));
                }
                else
                {
                    wt_results.push_back(0);
                }
            }
        }
    }

    // === Index text corpus ===

    std::string corpus;
    {
        std::ifstream f("/app/corpus.txt");
        std::stringstream ss;
        ss << f.rdbuf();
        corpus = ss.str();
    }

    csa_wt<wt_huff<>> csa1;
    construct_im(csa1, corpus, 1);
    int64_t size_csa_wt_huff = static_cast<int64_t>(size_in_bytes(csa1));

    csa_sada<> csa2;
    construct_im(csa2, corpus, 1);
    int64_t size_csa_sada = static_cast<int64_t>(size_in_bytes(csa2));

    csa_bitcompressed<> csa3;
    construct_im(csa3, corpus, 1);
    int64_t size_csa_bitcompressed = static_cast<int64_t>(size_in_bytes(csa3));

    std::string smallest = "csa_wt_huff";
    int64_t smallest_size = size_csa_wt_huff;
    if (size_csa_sada < smallest_size)
    {
        smallest = "csa_sada";
        smallest_size = size_csa_sada;
    }
    if (size_csa_bitcompressed < smallest_size)
    {
        smallest = "csa_bitcompressed";
    }

    // Process CSA queries
    std::vector<int64_t> csa_count_results;
    std::vector<std::vector<int64_t>> csa_locate_results;
    {
        std::ifstream qf("/app/csa_queries.txt");
        std::string line;
        while (std::getline(qf, line))
        {
            if (line.empty())
                continue;
            size_t space_pos = line.find(' ');
            std::string type = line.substr(0, space_pos);
            std::string pattern = line.substr(space_pos + 1);

            if (type == "COUNT")
            {
                auto cnt = count(csa1, pattern.begin(), pattern.end());
                csa_count_results.push_back(static_cast<int64_t>(cnt));
            }
            else if (type == "LOCATE")
            {
                auto occs = locate(csa1, pattern.begin(), pattern.end());
                std::sort(occs.begin(), occs.end());
                std::vector<int64_t> positions;
                size_t limit = std::min(occs.size(), static_cast<size_t>(20));
                for (size_t i = 0; i < limit; i++)
                    positions.push_back(static_cast<int64_t>(occs[i]));
                csa_locate_results.push_back(positions);
            }
        }
    }

    // Write JSON results
    std::ofstream out("/app/results.json");
    out << "{\n";

    out << "  \"wt_results\": [";
    for (size_t i = 0; i < wt_results.size(); i++)
    {
        if (i > 0)
            out << ", ";
        out << wt_results[i];
    }
    out << "],\n";

    out << "  \"csa_count_results\": [";
    for (size_t i = 0; i < csa_count_results.size(); i++)
    {
        if (i > 0)
            out << ", ";
        out << csa_count_results[i];
    }
    out << "],\n";

    out << "  \"csa_locate_results\": [\n";
    for (size_t i = 0; i < csa_locate_results.size(); i++)
    {
        if (i > 0)
            out << ",\n";
        out << "    [";
        for (size_t j = 0; j < csa_locate_results[i].size(); j++)
        {
            if (j > 0)
                out << ", ";
            out << csa_locate_results[i][j];
        }
        out << "]";
    }
    out << "\n  ],\n";

    out << "  \"csa_space\": {\n";
    out << "    \"csa_wt_huff\": " << size_csa_wt_huff << ",\n";
    out << "    \"csa_sada\": " << size_csa_sada << ",\n";
    out << "    \"csa_bitcompressed\": " << size_csa_bitcompressed << ",\n";
    out << "    \"smallest\": \"" << smallest << "\"\n";
    out << "  }\n";

    out << "}\n";
    out.close();

    return 0;
}
