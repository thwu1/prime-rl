// lattice_weight.h — Complete implementation of lattice weight semiring
//

#ifndef LATTICE_WEIGHT_H_
#define LATTICE_WEIGHT_H_

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <sstream>
#include <limits>
#include <vector>
#include <cassert>
#include <algorithm>
#include <unordered_set>
#include <string>

static constexpr float kDelta = 1.0f / 1024.0f;

enum DivideType { DIVIDE_LEFT = 0, DIVIDE_RIGHT = 1, DIVIDE_ANY = 2 };

// ---- Helpers for text I/O of floats ----

inline void WriteFloatType(std::ostream& strm, float f) {
    if (f == std::numeric_limits<float>::infinity())
        strm << "Infinity";
    else if (f == -std::numeric_limits<float>::infinity())
        strm << "-Infinity";
    else if (f != f)
        strm << "BadNumber";
    else
        strm << f;
}

inline void ReadFloatType(std::istream& strm, float& f) {
    std::string s;
    strm >> s;
    if (s == "Infinity") {
        f = std::numeric_limits<float>::infinity();
    } else if (s == "-Infinity") {
        f = -std::numeric_limits<float>::infinity();
    } else if (s == "BadNumber") {
        f = std::numeric_limits<float>::quiet_NaN();
    } else {
        char* p;
        f = std::strtof(s.c_str(), &p);
        if (p < s.c_str() + s.size())
            strm.clear(std::ios::badbit);
    }
}

// ---- Forward declarations ----

class LatticeWeight;
class CompactLatticeWeight;

inline int Compare(const LatticeWeight& a, const LatticeWeight& b);
inline LatticeWeight Plus(const LatticeWeight& a, const LatticeWeight& b);
inline LatticeWeight Times(const LatticeWeight& a, const LatticeWeight& b);
inline LatticeWeight Divide(const LatticeWeight& a, const LatticeWeight& b,
                            DivideType dt = DIVIDE_ANY);
inline bool ApproxEqual(const LatticeWeight& a, const LatticeWeight& b,
                        float delta = kDelta);

inline int Compare(const CompactLatticeWeight& a, const CompactLatticeWeight& b);
inline CompactLatticeWeight Plus(const CompactLatticeWeight& a,
                                 const CompactLatticeWeight& b);
inline CompactLatticeWeight Times(const CompactLatticeWeight& a,
                                  const CompactLatticeWeight& b);
inline CompactLatticeWeight Divide(const CompactLatticeWeight& a,
                                   const CompactLatticeWeight& b, DivideType dt);
inline bool ApproxEqual(const CompactLatticeWeight& a,
                        const CompactLatticeWeight& b, float delta = kDelta);

// ======================================================================
// LatticeWeight
// ======================================================================

class LatticeWeight {
 public:
    LatticeWeight() : value1_(0), value2_(0) {}
    LatticeWeight(float v1, float v2) : value1_(v1), value2_(v2) {}

    float Value1() const { return value1_; }
    float Value2() const { return value2_; }
    void SetValue1(float v) { value1_ = v; }
    void SetValue2(float v) { value2_ = v; }

    static LatticeWeight Zero() {
        return LatticeWeight(std::numeric_limits<float>::infinity(),
                             std::numeric_limits<float>::infinity());
    }
    static LatticeWeight One() { return LatticeWeight(0.0f, 0.0f); }

    bool Member() const {
        if (value1_ != value1_ || value2_ != value2_) return false;
        if (value1_ == -std::numeric_limits<float>::infinity() ||
            value2_ == -std::numeric_limits<float>::infinity()) return false;
        if (value1_ == std::numeric_limits<float>::infinity() ||
            value2_ == std::numeric_limits<float>::infinity()) {
            if (value1_ != std::numeric_limits<float>::infinity() ||
                value2_ != std::numeric_limits<float>::infinity()) return false;
        }
        return true;
    }

    LatticeWeight Quantize(float delta = kDelta) const {
        float sum = value1_ + value2_;
        if (sum == -std::numeric_limits<float>::infinity())
            return LatticeWeight(-std::numeric_limits<float>::infinity(),
                                 -std::numeric_limits<float>::infinity());
        if (sum == std::numeric_limits<float>::infinity())
            return LatticeWeight(std::numeric_limits<float>::infinity(),
                                 std::numeric_limits<float>::infinity());
        if (sum != sum)  // NaN
            return LatticeWeight(sum, sum);
        return LatticeWeight(std::floor(value1_ / delta + 0.5f) * delta,
                             std::floor(value2_ / delta + 0.5f) * delta);
    }

    LatticeWeight Reverse() const { return *this; }

    std::ostream& Write(std::ostream& os) const {
        os.write(reinterpret_cast<const char*>(&value1_), sizeof(float));
        os.write(reinterpret_cast<const char*>(&value2_), sizeof(float));
        return os;
    }

    std::istream& Read(std::istream& is) {
        is.read(reinterpret_cast<char*>(&value1_), sizeof(float));
        is.read(reinterpret_cast<char*>(&value2_), sizeof(float));
        return is;
    }

 private:
    float value1_, value2_;
};

// Compare: returns -1 if w1 has LARGER total cost (w1 is "less" in the
// semiring), +1 if w1 has SMALLER total cost (w1 is "greater" / preferred).
// This reverse convention ensures Plus(a,b) = (Compare(a,b)>=0 ? a : b)
// always picks the element with smaller cost.
inline int Compare(const LatticeWeight& w1, const LatticeWeight& w2) {
    float f1 = w1.Value1() + w1.Value2();
    float f2 = w2.Value1() + w2.Value2();
    if (f1 < f2) return 1;   // smaller cost -> larger in semiring
    if (f1 > f2) return -1;
    if (w1.Value1() < w2.Value1()) return 1;
    if (w1.Value1() > w2.Value1()) return -1;
    return 0;
}

inline LatticeWeight Plus(const LatticeWeight& w1, const LatticeWeight& w2) {
    return (Compare(w1, w2) >= 0) ? w1 : w2;
}

inline LatticeWeight Times(const LatticeWeight& w1, const LatticeWeight& w2) {
    return LatticeWeight(w1.Value1() + w2.Value1(),
                         w1.Value2() + w2.Value2());
}

inline LatticeWeight Divide(const LatticeWeight& w1, const LatticeWeight& w2,
                            DivideType) {
    float a = w1.Value1() - w2.Value1();
    float b = w1.Value2() - w2.Value2();
    if (a != a || b != b ||
        a == -std::numeric_limits<float>::infinity() ||
        b == -std::numeric_limits<float>::infinity())
        return LatticeWeight::Zero();
    if (a == std::numeric_limits<float>::infinity() ||
        b == std::numeric_limits<float>::infinity())
        return LatticeWeight::Zero();
    return LatticeWeight(a, b);
}

inline bool ApproxEqual(const LatticeWeight& w1, const LatticeWeight& w2,
                        float delta) {
    if (w1.Value1() == w2.Value1() && w1.Value2() == w2.Value2()) return true;
    return (std::fabs((w1.Value1() + w1.Value2()) -
                      (w2.Value1() + w2.Value2())) <= delta);
}

inline bool operator==(const LatticeWeight& a, const LatticeWeight& b) {
    volatile float va1 = a.Value1(), va2 = a.Value2();
    volatile float vb1 = b.Value1(), vb2 = b.Value2();
    return va1 == vb1 && va2 == vb2;
}
inline bool operator!=(const LatticeWeight& a, const LatticeWeight& b) {
    return !(a == b);
}

inline std::ostream& operator<<(std::ostream& os, const LatticeWeight& w) {
    WriteFloatType(os, w.Value1());
    os << ',';
    WriteFloatType(os, w.Value2());
    return os;
}

inline std::istream& operator>>(std::istream& strm, LatticeWeight& w) {
    int c;
    do { c = strm.get(); } while (std::isspace(c));
    std::string s1;
    while (c != ',' && c != EOF) {
        s1 += static_cast<char>(c);
        c = strm.get();
    }
    float v1, v2;
    std::istringstream ss1(s1);
    ReadFloatType(ss1, v1);
    ReadFloatType(strm, v2);
    w = LatticeWeight(v1, v2);
    return strm;
}

// ======================================================================
// NaturalLess
// ======================================================================

template<class W>
struct NaturalLess {
    bool operator()(const W& w1, const W& w2) const {
        return (Compare(w1, w2) == 1);
    }
};

// ======================================================================
// CompactLatticeWeight
// ======================================================================

class CompactLatticeWeight {
 public:
    CompactLatticeWeight() {}
    CompactLatticeWeight(const LatticeWeight& w, const std::vector<int32_t>& s)
        : weight_(w), string_(s) {}

    const LatticeWeight& Weight() const { return weight_; }
    const std::vector<int32_t>& String() const { return string_; }
    void SetWeight(const LatticeWeight& w) { weight_ = w; }
    void SetString(const std::vector<int32_t>& s) { string_ = s; }

    static CompactLatticeWeight Zero() {
        return CompactLatticeWeight(LatticeWeight::Zero(), {});
    }
    static CompactLatticeWeight One() {
        return CompactLatticeWeight(LatticeWeight::One(), {});
    }

    bool Member() const {
        if (!weight_.Member()) return false;
        if (weight_ == LatticeWeight::Zero()) return string_.empty();
        return true;
    }

    CompactLatticeWeight Quantize(float delta = kDelta) const {
        return CompactLatticeWeight(weight_.Quantize(delta), string_);
    }

    CompactLatticeWeight Reverse() const {
        std::vector<int32_t> v(string_.rbegin(), string_.rend());
        return CompactLatticeWeight(weight_, v);
    }

    std::ostream& Write(std::ostream& os) const {
        weight_.Write(os);
        int32_t sz = static_cast<int32_t>(string_.size());
        os.write(reinterpret_cast<const char*>(&sz), sizeof(int32_t));
        for (const auto& s : string_)
            os.write(reinterpret_cast<const char*>(&s), sizeof(int32_t));
        return os;
    }

    std::istream& Read(std::istream& is) {
        weight_.Read(is);
        int32_t sz;
        is.read(reinterpret_cast<char*>(&sz), sizeof(int32_t));
        string_.resize(sz);
        for (auto& s : string_)
            is.read(reinterpret_cast<char*>(&s), sizeof(int32_t));
        return is;
    }

 private:
    LatticeWeight weight_;
    std::vector<int32_t> string_;
};

inline int Compare(const CompactLatticeWeight& w1,
                   const CompactLatticeWeight& w2) {
    int c1 = Compare(w1.Weight(), w2.Weight());
    if (c1 != 0) return c1;
    int l1 = static_cast<int>(w1.String().size());
    int l2 = static_cast<int>(w2.String().size());
    // Reverse order on string lengths: shorter string is "greater" (preferred)
    if (l1 > l2) return -1;
    if (l1 < l2) return 1;
    for (int i = 0; i < l1; i++) {
        if (w1.String()[i] < w2.String()[i]) return -1;
        if (w1.String()[i] > w2.String()[i]) return 1;
    }
    return 0;
}

inline CompactLatticeWeight Plus(const CompactLatticeWeight& w1,
                                 const CompactLatticeWeight& w2) {
    return (Compare(w1, w2) >= 0) ? w1 : w2;
}

inline CompactLatticeWeight Times(const CompactLatticeWeight& w1,
                                  const CompactLatticeWeight& w2) {
    LatticeWeight w = Times(w1.Weight(), w2.Weight());
    if (w == LatticeWeight::Zero())
        return CompactLatticeWeight::Zero();
    std::vector<int32_t> v;
    v.reserve(w1.String().size() + w2.String().size());
    v.insert(v.end(), w1.String().begin(), w1.String().end());
    v.insert(v.end(), w2.String().begin(), w2.String().end());
    return CompactLatticeWeight(w, v);
}

inline CompactLatticeWeight Divide(const CompactLatticeWeight& w1,
                                   const CompactLatticeWeight& w2,
                                   DivideType div) {
    if (w1.Weight() == LatticeWeight::Zero()) {
        return CompactLatticeWeight::Zero();
    }
    LatticeWeight w = Divide(w1.Weight(), w2.Weight());
    const auto& v1 = w1.String();
    const auto& v2 = w2.String();
    assert(v2.size() <= v1.size());
    if (div == DIVIDE_LEFT) {
        assert(std::equal(v2.begin(), v2.end(), v1.begin()));
        return CompactLatticeWeight(w,
            std::vector<int32_t>(v1.begin() + static_cast<int>(v2.size()),
                                 v1.end()));
    } else {
        assert(std::equal(v2.begin(), v2.end(),
                          v1.end() - static_cast<int>(v2.size())));
        return CompactLatticeWeight(w,
            std::vector<int32_t>(v1.begin(),
                                 v1.end() - static_cast<int>(v2.size())));
    }
}

inline bool ApproxEqual(const CompactLatticeWeight& w1,
                        const CompactLatticeWeight& w2, float delta) {
    return ApproxEqual(w1.Weight(), w2.Weight(), delta) &&
           w1.String() == w2.String();
}

inline bool operator==(const CompactLatticeWeight& a,
                       const CompactLatticeWeight& b) {
    return a.Weight() == b.Weight() && a.String() == b.String();
}
inline bool operator!=(const CompactLatticeWeight& a,
                       const CompactLatticeWeight& b) {
    return !(a == b);
}

inline std::ostream& operator<<(std::ostream& os,
                                const CompactLatticeWeight& w) {
    os << w.Weight() << ',';
    for (size_t i = 0; i < w.String().size(); i++) {
        if (i > 0) os << '_';
        os << w.String()[i];
    }
    return os;
}

inline std::istream& operator>>(std::istream& strm, CompactLatticeWeight& w) {
    std::string s;
    strm >> s;
    if (strm.fail()) return strm;
    size_t pos = s.find_last_of(',');
    if (pos == std::string::npos) {
        strm.clear(std::ios::badbit);
        return strm;
    }
    std::string s1(s, 0, pos), s2(s, pos + 1);
    LatticeWeight weight;
    std::istringstream ss1(s1);
    ss1 >> weight;
    w.SetWeight(weight);
    std::vector<int32_t> str;
    const char* c = s2.c_str();
    while (*c != '\0') {
        if (*c == '_') c++;
        char* c2;
        long int i = strtol(c, &c2, 10);
        if (c2 == c) break;
        c = c2;
        str.push_back(static_cast<int32_t>(i));
    }
    w.SetString(str);
    return strm;
}

// ======================================================================
// CompactLatticeWeightCommonDivisor
// ======================================================================

struct CompactLatticeWeightCommonDivisor {
    CompactLatticeWeight operator()(const CompactLatticeWeight& w1,
                                    const CompactLatticeWeight& w2) const {
        auto s1b = w1.String().begin(), s1e = w1.String().end();
        auto s2b = w2.String().begin(), s2e = w2.String().end();
        auto s1i = s1b, s2i = s2b;
        while (s1i < s1e && s2i < s2e && *s1i == *s2i) {
            ++s1i; ++s2i;
        }
        return CompactLatticeWeight(Plus(w1.Weight(), w2.Weight()),
                                    std::vector<int32_t>(s1b, s1i));
    }
};

// ======================================================================
// LatticeStringRepository
// ======================================================================

template<class IntType>
class LatticeStringRepository {
 public:
    struct Entry {
        const Entry* parent;
        IntType i;
        bool operator==(const Entry& other) const {
            return (parent == other.parent && i == other.i);
        }
        Entry() : parent(nullptr), i(0) {}
        Entry(const Entry& e) : parent(e.parent), i(e.i) {}
    };

    const Entry* EmptyString() { return nullptr; }

    const Entry* Successor(const Entry* parent, IntType i) {
        new_entry_->parent = parent;
        new_entry_->i = i;
        auto pr = set_.insert(new_entry_);
        if (pr.second) {
            const Entry* ans = new_entry_;
            new_entry_ = new Entry();
            return ans;
        } else {
            return *pr.first;
        }
    }

    const Entry* Concatenate(const Entry* a, const Entry* b) {
        if (a == nullptr) return b;
        if (b == nullptr) return a;
        std::vector<IntType> v;
        ConvertToVector(b, &v);
        const Entry* ans = a;
        for (size_t i = 0; i < v.size(); i++)
            ans = Successor(ans, v[i]);
        return ans;
    }

    const Entry* CommonPrefix(const Entry* a, const Entry* b) {
        std::vector<IntType> a_vec, b_vec;
        ConvertToVector(a, &a_vec);
        ConvertToVector(b, &b_vec);
        const Entry* ans = nullptr;
        for (size_t i = 0; i < a_vec.size() && i < b_vec.size() &&
             a_vec[i] == b_vec[i]; i++)
            ans = Successor(ans, a_vec[i]);
        return ans;
    }

    void ReduceToCommonPrefix(const Entry* a, std::vector<IntType>* b) {
        size_t a_size = Size(a), b_size = b->size();
        while (a_size > b_size) {
            a = a->parent;
            a_size--;
        }
        if (b_size > a_size)
            b_size = a_size;
        typename std::vector<IntType>::iterator b_begin = b->begin();
        while (a_size != 0) {
            if (a->i != *(b_begin + a_size - 1))
                b_size = a_size - 1;
            a = a->parent;
            a_size--;
        }
        if (b_size != b->size())
            b->resize(b_size);
    }

    const Entry* RemovePrefix(const Entry* a, size_t n) {
        if (n == 0) return a;
        std::vector<IntType> a_vec;
        ConvertToVector(a, &a_vec);
        assert(a_vec.size() >= n);
        const Entry* ans = nullptr;
        for (size_t i = n; i < a_vec.size(); i++)
            ans = Successor(ans, a_vec[i]);
        return ans;
    }

    bool IsPrefixOf(const Entry* a, const Entry* b) const {
        if (a == nullptr) return true;
        if (a == b) return true;
        if (b == nullptr) return false;
        return IsPrefixOf(a, b->parent);
    }

    size_t Size(const Entry* entry) const {
        size_t ans = 0;
        while (entry != nullptr) { ans++; entry = entry->parent; }
        return ans;
    }

    void ConvertToVector(const Entry* entry, std::vector<IntType>* out) const {
        size_t length = Size(entry);
        out->resize(length);
        if (entry != nullptr) {
            auto iter = out->rbegin();
            while (entry != nullptr) {
                *iter = entry->i;
                entry = entry->parent;
                ++iter;
            }
        }
    }

    const Entry* ConvertFromVector(const std::vector<IntType>& vec) {
        const Entry* e = nullptr;
        for (size_t i = 0; i < vec.size(); i++)
            e = Successor(e, vec[i]);
        return e;
    }

    LatticeStringRepository() { new_entry_ = new Entry; }

    void Destroy() {
        for (auto iter = set_.begin(); iter != set_.end(); ++iter)
            delete *iter;
        SetType tmp;
        tmp.swap(set_);
        if (new_entry_) { delete new_entry_; new_entry_ = nullptr; }
    }

    void Rebuild(const std::vector<const Entry*>& to_keep) {
        SetType tmp_set;
        for (auto iter = to_keep.begin(); iter != to_keep.end(); ++iter)
            RebuildHelper(*iter, &tmp_set);
        for (auto iter = set_.begin(); iter != set_.end(); ++iter) {
            if (tmp_set.count(*iter) == 0)
                delete (*iter);
        }
        set_.swap(tmp_set);
    }

    ~LatticeStringRepository() { Destroy(); }

    int32_t MemSize() const {
        return static_cast<int32_t>(set_.size() * sizeof(Entry) * 2);
    }

 private:
    class EntryKey {
     public:
        size_t operator()(const Entry* entry) const {
            size_t prime = 49109;
            return static_cast<size_t>(entry->i) +
                   prime * reinterpret_cast<size_t>(entry->parent);
        }
    };
    class EntryEqual {
     public:
        bool operator()(const Entry* e1, const Entry* e2) const {
            return (*e1 == *e2);
        }
    };
    typedef std::unordered_set<const Entry*, EntryKey, EntryEqual> SetType;

    void RebuildHelper(const Entry* to_add, SetType* tmp_set) {
        while (true) {
            if (to_add == nullptr) return;
            auto iter = tmp_set->find(to_add);
            if (iter == tmp_set->end()) {
                tmp_set->insert(to_add);
                to_add = to_add->parent;
            } else {
                return;
            }
        }
    }

    LatticeStringRepository(const LatticeStringRepository&) = delete;
    LatticeStringRepository& operator=(const LatticeStringRepository&) = delete;

    Entry* new_entry_;
    SetType set_;
};

#endif  // LATTICE_WEIGHT_H_
