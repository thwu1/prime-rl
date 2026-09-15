/* Exact Model Counter for MC Competition DIMACS format.
 * Compiled with: g++ -O2 -Wall -std=c++17 -o mc mc.cpp -lgmpxx -lgmp
 *
 */

#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <set>
#include <map>
#include <unordered_map>
#include <algorithm>
#include <functional>
#include <cstdlib>
#include <gmpxx.h>

using namespace std;

/* ---------- weight parsing ---------- */

mpq_class parse_decimal(const string& s) {
    size_t dot = s.find('.');
    if (dot == string::npos) return mpq_class(s);

    string ip = s.substr(0, dot);
    string fp = s.substr(dot + 1);
    if (ip.empty()) ip = "0";

    bool neg = (!ip.empty() && ip[0] == '-');
    string aip = neg ? ip.substr(1) : ip;
    if (aip.empty()) aip = "0";

    mpz_class num(aip + fp);
    if (neg) num = -num;
    mpz_class den;
    mpz_ui_pow_ui(den.get_mpz_t(), 10, fp.length());
    mpq_class r(num, den);
    r.canonicalize();
    return r;
}

mpq_class parse_weight(const string& s) {
    /* fraction: P/Q */
    size_t sl = s.find('/');
    if (sl != string::npos) {
        mpz_class num(s.substr(0, sl));
        mpz_class den(s.substr(sl + 1));
        mpq_class r(num, den);
        r.canonicalize();
        return r;
    }

    /* scientific: XeY or XEY */
    size_t ep = s.find('e');
    if (ep == string::npos) ep = s.find('E');
    if (ep != string::npos) {
        mpq_class mant = parse_decimal(s.substr(0, ep));
        int exp = stoi(s.substr(ep + 1));
        mpz_class tp;
        mpz_ui_pow_ui(tp.get_mpz_t(), 10, abs(exp));
        if (exp >= 0) mant *= mpq_class(tp);
        else          mant /= mpq_class(tp);
        mant.canonicalize();
        return mant;
    }

    return parse_decimal(s);
}

/* ---------- DIMACS parser ---------- */

struct Instance {
    int nvars = 0, nclauses = 0;
    bool weighted = false;
    vector<vector<int>> clauses;
    map<int, mpq_class> weights;
};

Instance parse_dimacs(const string& fname) {
    Instance inst;
    ifstream f(fname);
    if (!f) { cerr << "Cannot open " << fname << "\n"; exit(1); }

    string line;
    while (getline(f, line)) {
        if (line.empty()) continue;
        if (line[0] == 'c') {
            istringstream iss(line);
            string c_tok; iss >> c_tok;
            string tok;
            if (!(iss >> tok)) continue;
            if (tok == "t") {
                string track; iss >> track;
                if (track == "wmc") inst.weighted = true;
            } else if (tok == "p") {
                string dir; iss >> dir;
                if (dir == "weight") {
                    int lit; string ws;
                    if (iss >> lit >> ws)
                        inst.weights[lit] = parse_weight(ws);
                }
            }
        } else if (line[0] == 'p') {
            istringstream iss(line);
            string p, cnf;
            iss >> p >> cnf >> inst.nvars >> inst.nclauses;
        } else {
            istringstream iss(line);
            vector<int> cl;
            int l;
            while (iss >> l && l != 0) cl.push_back(l);
            if (!cl.empty()) inst.clauses.push_back(cl);
        }
    }
    return inst;
}

/* ---------- model counter ---------- */

class Counter {
    Instance& inst;
    unordered_map<string, mpq_class> cache;

    mpq_class w(int lit) {
        if (!inst.weighted) return mpq_class(1);
        auto it = inst.weights.find(lit);
        return it != inst.weights.end() ? it->second : mpq_class(1);
    }

    mpq_class free_w(int var) {
        return inst.weighted ? w(var) + w(-var) : mpq_class(2);
    }

    /* Simplify clauses by assigning var=val.
       Returns {new_clauses, conflict}. */
    pair<vector<vector<int>>, bool> assign(
            const vector<vector<int>>& cls, int var, bool val) {
        int tl = val ? var : -var;
        int fl = val ? -var : var;
        vector<vector<int>> out;
        for (auto& c : cls) {
            bool sat = false;
            vector<int> nc;
            for (int l : c) {
                if (l == tl) { sat = true; break; }
                if (l != fl) nc.push_back(l);
            }
            if (sat) continue;
            if (nc.empty()) return {{}, true};
            out.push_back(nc);
        }
        return {out, false};
    }

    /* Unit propagation.  Returns {factor, clauses, vars, conflict}. */
    struct UP {
        mpq_class factor;
        vector<vector<int>> cls;
        set<int> vars;
        bool conflict;
    };

    UP propagate(vector<vector<int>> cls, set<int> vars) {
        UP r;
        r.factor = 1;
        r.conflict = false;
        bool go = true;
        while (go) {
            go = false;
            for (auto& c : cls) {
                if (c.size() == 1) {
                    int lit = c[0], v = abs(lit);
                    r.factor *= w(lit);
                    vars.erase(v);
                    auto [nc, conf] = assign(cls, v, lit > 0);
                    if (conf) { r.conflict = true; return r; }
                    cls = nc;
                    go = true;
                    break;
                }
            }
        }
        r.cls = cls;
        r.vars = vars;
        return r;
    }

    /* Connected components via union-find. */
    vector<pair<vector<vector<int>>, set<int>>> components(
            const vector<vector<int>>& cls) {
        map<int, int> par;
        set<int> cv;
        for (auto& c : cls)
            for (int l : c) { int v = abs(l); cv.insert(v); par[v] = v; }

        function<int(int)> find = [&](int x) -> int {
            return par[x] == x ? x : par[x] = find(par[x]);
        };

        for (auto& c : cls) {
            int f = abs(c[0]);
            for (size_t i = 1; i < c.size(); i++) {
                int a = find(f), b = find(abs(c[i]));
                if (a != b) par[a] = b;
            }
        }

        map<int, vector<vector<int>>> cc;
        map<int, set<int>> ccv;
        for (auto& c : cls) {
            int root = find(abs(c[0]));
            cc[root].push_back(c);
            for (int l : c) ccv[root].insert(abs(l));
        }

        vector<pair<vector<vector<int>>, set<int>>> out;
        for (auto& [root, c] : cc)
            out.push_back({c, ccv[root]});
        return out;
    }

    string cache_key(const vector<vector<int>>& cls) {
        auto sc = cls;
        for (auto& c : sc) sort(c.begin(), c.end());
        sort(sc.begin(), sc.end());
        string k;
        for (auto& c : sc) {
            for (int l : c) { k += to_string(l); k += ','; }
            k += ';';
        }
        return k;
    }

public:
    Counter(Instance& i) : inst(i) {}

    mpq_class count(vector<vector<int>> cls, set<int> vars) {
        /* unit propagation */
        auto up = propagate(cls, vars);
        if (up.conflict) return mpq_class(0);
        cls = up.cls;
        vars = up.vars;

        /* all clauses satisfied */
        if (cls.empty()) {
            mpq_class r = up.factor;
            for (int v : vars) r *= free_w(v);
            return r;
        }

        /* identify clause variables and free variables */
        set<int> cv;
        for (auto& c : cls) for (int l : c) cv.insert(abs(l));
        mpq_class ff(1);
        for (int v : vars)
            if (!cv.count(v)) ff *= free_w(v);

        /* component decomposition */
        auto comps = components(cls);
        if (comps.size() > 1) {
            mpq_class r = up.factor * ff;
            for (auto& [cc, ccv] : comps)
                r *= count(cc, ccv);
            return r;
        }

        /* cache lookup */
        string key = cache_key(cls);
        auto it = cache.find(key);
        if (it != cache.end())
            return up.factor * ff * it->second;

        /* branch on most-frequent variable */
        map<int, int> freq;
        for (auto& c : cls) for (int l : c) freq[abs(l)]++;
        int bv = 0, bf = 0;
        for (auto& [v, f] : freq)
            if (f > bf) { bf = f; bv = v; }

        set<int> inner = cv;
        inner.erase(bv);

        mpq_class ct(0), cf(0);
        {
            auto [tc, tconf] = assign(cls, bv, true);
            if (!tconf) ct = w(bv) * count(tc, inner);
        }
        {
            auto [fc, fconf] = assign(cls, bv, false);
            if (!fconf) cf = w(-bv) * count(fc, inner);
        }

        mpq_class comp = ct + cf;
        cache[key] = comp;
        return up.factor * ff * comp;
    }

    pair<bool, mpq_class> solve() {
        set<int> all;
        for (int i = 1; i <= inst.nvars; i++) all.insert(i);
        mpq_class r = count(inst.clauses, all);
        return {r != 0, r};
    }
};

/* ---------- main ---------- */

int main(int argc, char** argv) {
    if (argc != 2) {
        cerr << "Usage: mc <file.cnf>\n";
        return 1;
    }
    Instance inst = parse_dimacs(argv[1]);
    Counter c(inst);
    auto [sat, cnt] = c.solve();

    cout << (sat ? "s SATISFIABLE" : "s UNSATISFIABLE") << "\n";
    if (inst.weighted) {
        cout << "c s type wmc\n";
        cnt.canonicalize();
        cout << "c s exact rational "
             << cnt.get_num() << "/" << cnt.get_den() << "\n";
    } else {
        cout << "c s type mc\n";
        cout << "c s exact arb int " << cnt.get_num() << "\n";
    }
    return 0;
}
