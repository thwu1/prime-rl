/*
 * tqdist.cpp -- Quartet agreement calculator for phylogenetic trees
 *
 * Reads a multi-tree Newick file and computes quartet agreement statistics
 * for all pairs (including self-comparisons on the diagonal).
 *
 * Inspired by: Sand, Holt, Johansen, Brodal, Mailund & Pedersen,
 * "tqDist: a library for computing the quartet and triplet distances
 * between binary or general trees", Bioinformatics 30(14), 2014.
 *
 */

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

using namespace std;
using I64 = int64_t;

struct Node {
    string label;
    vector<Node*> children;
    Node(const string& l = "") : label(l) {}
    ~Node() { for (auto* c : children) delete c; }
    bool isLeaf() const { return children.empty(); }
};

class NewickParser {
    string s;
    size_t pos;

    string readName() {
        size_t start = pos;
        while (pos < s.size() && s[pos] != '(' && s[pos] != ')' &&
               s[pos] != ',' && s[pos] != ':' && s[pos] != ';')
            pos++;
        return s.substr(start, pos - start);
    }

    void skipBranchLength() {
        if (pos < s.size() && s[pos] == ':') {
            pos++;
            while (pos < s.size() && s[pos] != '(' && s[pos] != ')' &&
                   s[pos] != ',' && s[pos] != ':' && s[pos] != ';')
                pos++;
        }
    }

    Node* parseSubtree() {
        if (pos < s.size() && s[pos] == '(')
            return parseInternal();
        return new Node(readName());
    }

    Node* parseInternal() {
        pos++;
        auto* nd = new Node();
        while (true) {
            nd->children.push_back(parseSubtree());
            skipBranchLength();
            if (pos < s.size() && s[pos] == ',') { pos++; continue; }
            break;
        }
        if (pos < s.size() && s[pos] == ')') pos++;
        nd->label = readName();
        return nd;
    }

public:
    Node* parse(const string& newick) {
        s.clear();
        for (char c : newick)
            if (!isspace(c)) s += c;
        if (s.empty()) return nullptr;
        if (s.back() == ';') s.pop_back();
        if (s.empty()) return nullptr;
        pos = 0;
        Node* root = parseSubtree();
        skipBranchLength();
        return root;
    }
};

void collectLeaves(const Node* n, vector<string>& out) {
    if (n->isLeaf()) { out.push_back(n->label); return; }
    for (const auto* c : n->children) collectLeaves(c, out);
}

struct Split {
    vector<bool> bits;
};

vector<bool> computeSplits(const Node* n,
                           const vector<string>& sortedLeaves,
                           int nLeaves,
                           vector<Split>& splits) {
    vector<bool> desc(nLeaves, false);
    if (n->isLeaf()) {
        for (int i = 0; i < nLeaves; i++)
            if (sortedLeaves[i] == n->label) { desc[i] = true; break; }
        return desc;
    }
    vector<vector<bool>> childDescs;
    for (const auto* c : n->children) {
        childDescs.push_back(computeSplits(c, sortedLeaves, nLeaves, splits));
        for (int i = 0; i < nLeaves; i++)
            if (childDescs.back()[i]) desc[i] = true;
    }
    for (const auto& cd : childDescs) {
        int cnt = 0;
        for (int i = 0; i < nLeaves; i++) if (cd[i]) cnt++;
        if (cnt >= 2 && (nLeaves - cnt) >= 2)
            splits.push_back({cd});
    }
    return desc;
}

int quartetState(const vector<Split>& splits, int a, int b, int c, int d) {
    for (const auto& sp : splits) {
        int cnt = (int)sp.bits[a] + sp.bits[b] + sp.bits[c] + sp.bits[d];
        if (cnt != 2) continue;
        if (sp.bits[a] == sp.bits[b]) return 0;
        if (sp.bits[a] == sp.bits[c]) return 1;
        return 2;
    }
    return -1;
}

I64 comb4(int n) {
    if (n < 4) return 0;
    return (I64)n * (n - 1) * (n - 2) * (n - 3) / 24;
}

int main(int argc, char* argv[]) {
    if (argc != 2) {
        cerr << "Usage: " << argv[0] << " <trees.nwk>" << endl;
        return 1;
    }

    ifstream fin(argv[1]);
    if (!fin) { cerr << "Cannot open " << argv[1] << endl; return 1; }

    vector<string> treeStrs;
    string line;
    while (getline(fin, line)) {
        size_t a = line.find_first_not_of(" \t\r\n");
        if (a == string::npos) continue;
        size_t b = line.find_last_not_of(" \t\r\n");
        treeStrs.push_back(line.substr(a, b - a + 1));
    }
    fin.close();

    if (treeStrs.empty()) { cerr << "No trees" << endl; return 1; }

    NewickParser parser;
    vector<Node*> trees;
    for (auto& ts : treeStrs) {
        Node* t = parser.parse(ts);
        if (!t) { cerr << "Parse failed: " << ts << endl; return 1; }
        trees.push_back(t);
    }

    vector<string> leaves;
    collectLeaves(trees[0], leaves);
    sort(leaves.begin(), leaves.end());
    int n = (int)leaves.size();

    if (n < 4) { cerr << "Need >= 4 leaves" << endl; return 1; }

    for (size_t t = 1; t < trees.size(); t++) {
        vector<string> tl;
        collectLeaves(trees[t], tl);
        sort(tl.begin(), tl.end());
        if (tl != leaves) {
            cerr << "Tree " << t << ": leaf set mismatch" << endl;
            return 1;
        }
    }

    int nTrees = (int)trees.size();
    vector<vector<Split>> allSplits(nTrees);
    for (int t = 0; t < nTrees; t++)
        computeSplits(trees[t], leaves, n, allSplits[t]);

    I64 Q = comb4(n);
    for (int i = 0; i < nTrees; i++) {
        for (int j = 0; j <= i; j++) {
            I64 agree = 0, unres = 0;
            for (int a = 0; a < n; a++)
                for (int b = a + 1; b < n; b++)
                    for (int c = b + 1; c < n; c++)
                        for (int d = c + 1; d < n; d++) {
                            int s1 = quartetState(allSplits[i], a, b, c, d);
                            int s2 = quartetState(allSplits[j], a, b, c, d);
                            if (s1 >= 0 && s2 >= 0 && s1 == s2) agree++;
                            else if (s1 < 0 && s2 < 0) unres++;
                        }
            cout << i << " " << j << " " << agree << " " << unres << " " << Q << "\n";
        }
    }

    for (auto* t : trees) delete t;
    return 0;
}
