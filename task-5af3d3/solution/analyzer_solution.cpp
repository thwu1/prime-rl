#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include <sdsl/suffix_arrays.hpp>
#include <sdsl/wavelet_trees.hpp>

using namespace sdsl;
using namespace std;

// Helper: count of value c in positions [l, r) via rank
static int64_t freq_in_range(wt_int<> & wt, uint64_t l, uint64_t r, uint64_t c)
{
    return static_cast<int64_t>(wt.rank(r, c)) - static_cast<int64_t>(wt.rank(l, c));
}

// QUANTILE: k-th smallest (0-indexed) in [l, r)
// Iterate values in ascending order, accumulating frequencies.
static int64_t range_quantile(wt_int<> & wt, int64_t l, int64_t r, int64_t k, int64_t max_val)
{
    int64_t cumulative = 0;
    for (int64_t v = 0; v <= max_val; v++)
    {
        int64_t f = freq_in_range(wt, l, r, v);
        cumulative += f;
        if (cumulative > k)
            return v;
    }
    return -1;
}

// DISTINCT: count distinct values in [l, r)
static int64_t range_distinct(wt_int<> & wt, int64_t l, int64_t r, int64_t max_val)
{
    int64_t cnt = 0;
    for (int64_t v = 0; v <= max_val; v++)
    {
        if (freq_in_range(wt, l, r, v) > 0)
            cnt++;
    }
    return cnt;
}

// TOPFREQ: most frequent value in [l, r); ties by smallest value
static int64_t range_topfreq(wt_int<> & wt, int64_t l, int64_t r, int64_t max_val)
{
    int64_t best_val = -1, best_freq = -1;
    for (int64_t v = 0; v <= max_val; v++)
    {
        int64_t f = freq_in_range(wt, l, r, v);
        if (f > best_freq)
        {
            best_freq = f;
            best_val = v;
        }
    }
    return best_val;
}

// PREVVAL: largest value <= v in [l, r), or -1
static int64_t range_prevval(wt_int<> & wt, int64_t l, int64_t r, int64_t v, int64_t max_val)
{
    int64_t upper = (v < max_val) ? v : max_val;
    for (int64_t c = upper; c >= 0; c--)
    {
        if (freq_in_range(wt, l, r, c) > 0)
            return c;
    }
    return -1;
}

// NEXTVAL: smallest value >= v in [l, r), or -1
static int64_t range_nextval(wt_int<> & wt, int64_t l, int64_t r, int64_t v, int64_t max_val)
{
    int64_t lower = (v > 0) ? v : 0;
    for (int64_t c = lower; c <= max_val; c++)
    {
        if (freq_in_range(wt, l, r, c) > 0)
            return c;
    }
    return -1;
}

int main()
{
    // ========== Read integer sequence ==========
    vector<uint64_t> raw_seq;
    {
        ifstream f("/app/sequence.txt");
        uint64_t val;
        while (f >> val)
            raw_seq.push_back(val);
    }
    int64_t max_val = static_cast<int64_t>(*max_element(raw_seq.begin(), raw_seq.end()));

    int_vector<> iv(raw_seq.size());
    for (size_t i = 0; i < raw_seq.size(); i++)
        iv[i] = raw_seq[i];
    util::bit_compress(iv);

    // Build primary wavelet tree (default bit_vector backing)
    wt_int<> wt;
    construct_im(wt, iv);

    // ========== Process range queries ==========
    vector<int64_t> range_results;
    {
        ifstream qf("/app/range_queries.txt");
        string line;
        while (getline(qf, line))
        {
            if (line.empty())
                continue;
            istringstream iss(line);
            string type;
            iss >> type;

            if (type == "QUANTILE")
            {
                int64_t l, r, k;
                iss >> l >> r >> k;
                range_results.push_back(range_quantile(wt, l, r, k, max_val));
            }
            else if (type == "DISTINCT")
            {
                int64_t l, r;
                iss >> l >> r;
                range_results.push_back(range_distinct(wt, l, r, max_val));
            }
            else if (type == "TOPFREQ")
            {
                int64_t l, r;
                iss >> l >> r;
                range_results.push_back(range_topfreq(wt, l, r, max_val));
            }
            else if (type == "PREVVAL")
            {
                int64_t l, r, v;
                iss >> l >> r >> v;
                range_results.push_back(range_prevval(wt, l, r, v, max_val));
            }
            else if (type == "NEXTVAL")
            {
                int64_t l, r, v;
                iss >> l >> r >> v;
                range_results.push_back(range_nextval(wt, l, r, v, max_val));
            }
        }
    }

    // ========== WT space analysis ==========
    wt_int<rrr_vector<63>> wt_rrr63;
    construct_im(wt_rrr63, iv);
    wt_int<rrr_vector<15>> wt_rrr15;
    construct_im(wt_rrr15, iv);

    int64_t sz_wt_bv = static_cast<int64_t>(size_in_bytes(wt));
    int64_t sz_wt_rrr63 = static_cast<int64_t>(size_in_bytes(wt_rrr63));
    int64_t sz_wt_rrr15 = static_cast<int64_t>(size_in_bytes(wt_rrr15));

    string smallest_wt = "wt_bit_vector";
    int64_t smallest_wt_sz = sz_wt_bv;
    if (sz_wt_rrr63 < smallest_wt_sz)
    {
        smallest_wt = "wt_rrr_63";
        smallest_wt_sz = sz_wt_rrr63;
    }
    if (sz_wt_rrr15 < smallest_wt_sz)
    {
        smallest_wt = "wt_rrr_15";
        smallest_wt_sz = sz_wt_rrr15;
    }

    // ========== Read text corpus ==========
    string corpus;
    {
        ifstream f("/app/corpus.txt");
        stringstream ss;
        ss << f.rdbuf();
        corpus = ss.str();
    }

    // ========== CSA variants ==========
    csa_wt<wt_huff<>> csa1;
    construct_im(csa1, corpus, 1);
    csa_sada<> csa2;
    construct_im(csa2, corpus, 1);
    csa_bitcompressed<> csa3;
    construct_im(csa3, corpus, 1);

    int64_t sz_csa_huff = static_cast<int64_t>(size_in_bytes(csa1));
    int64_t sz_csa_sada = static_cast<int64_t>(size_in_bytes(csa2));
    int64_t sz_csa_bitc = static_cast<int64_t>(size_in_bytes(csa3));

    string smallest_csa = "csa_wt_huff";
    int64_t smallest_csa_sz = sz_csa_huff;
    if (sz_csa_sada < smallest_csa_sz)
    {
        smallest_csa = "csa_sada";
        smallest_csa_sz = sz_csa_sada;
    }
    if (sz_csa_bitc < smallest_csa_sz)
    {
        smallest_csa = "csa_bitcompressed";
        smallest_csa_sz = sz_csa_bitc;
    }

    // ========== Process text queries ==========
    vector<int64_t> text_count_results;
    vector<vector<int64_t>> text_locate_results;
    {
        ifstream qf("/app/text_queries.txt");
        string line;
        while (getline(qf, line))
        {
            if (line.empty())
                continue;
            size_t space_pos = line.find(' ');
            string type = line.substr(0, space_pos);
            string rest = line.substr(space_pos + 1);

            if (type == "COUNT")
            {
                string pattern = rest;
                auto cnt = count(csa1, pattern.begin(), pattern.end());
                text_count_results.push_back(static_cast<int64_t>(cnt));
            }
            else if (type == "LOCATE")
            {
                // format: LOCATE pattern k
                size_t sp2 = rest.rfind(' ');
                string pattern = rest.substr(0, sp2);
                int64_t k = stoll(rest.substr(sp2 + 1));
                auto occs = locate(csa1, pattern.begin(), pattern.end());
                sort(occs.begin(), occs.end());
                vector<int64_t> positions;
                size_t limit = min(occs.size(), static_cast<size_t>(k));
                for (size_t i = 0; i < limit; i++)
                    positions.push_back(static_cast<int64_t>(occs[i]));
                text_locate_results.push_back(positions);
            }
        }
    }

    // ========== Write JSON ==========
    ofstream out("/app/results.json");
    out << "{\n";

    out << "  \"range_results\": [";
    for (size_t i = 0; i < range_results.size(); i++)
    {
        if (i > 0)
            out << ", ";
        out << range_results[i];
    }
    out << "],\n";

    out << "  \"text_count_results\": [";
    for (size_t i = 0; i < text_count_results.size(); i++)
    {
        if (i > 0)
            out << ", ";
        out << text_count_results[i];
    }
    out << "],\n";

    out << "  \"text_locate_results\": [\n";
    for (size_t i = 0; i < text_locate_results.size(); i++)
    {
        if (i > 0)
            out << ",\n";
        out << "    [";
        for (size_t j = 0; j < text_locate_results[i].size(); j++)
        {
            if (j > 0)
                out << ", ";
            out << text_locate_results[i][j];
        }
        out << "]";
    }
    out << "\n  ],\n";

    out << "  \"space_analysis\": {\n";
    out << "    \"wt_bit_vector\": " << sz_wt_bv << ",\n";
    out << "    \"wt_rrr_63\": " << sz_wt_rrr63 << ",\n";
    out << "    \"wt_rrr_15\": " << sz_wt_rrr15 << ",\n";
    out << "    \"csa_wt_huff\": " << sz_csa_huff << ",\n";
    out << "    \"csa_sada\": " << sz_csa_sada << ",\n";
    out << "    \"csa_bitcompressed\": " << sz_csa_bitc << ",\n";
    out << "    \"smallest_wt\": \"" << smallest_wt << "\",\n";
    out << "    \"smallest_csa\": \"" << smallest_csa << "\"\n";
    out << "  }\n";

    out << "}\n";
    out.close();

    return 0;
}
