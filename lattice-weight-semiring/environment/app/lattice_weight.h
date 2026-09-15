// lattice_weight.h — Lattice weight semiring and string repository
// Implement all methods marked TODO to make tests pass.
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

    // TODO: implement
    LatticeWeight Quantize(float delta = kDelta) const {
        (void)delta;
        return *this;
    }

    // TODO: implement
    LatticeWeight Reverse() const {
        return *this;
    }

    // TODO: implement binary I/O
    std::ostream& Write(std::ostream& os) const { return os; }
    std::istream& Read(std::istream& is) { return is; }

 private:
    float value1_, value2_;
};

// TODO: implement Compare — must be consistent with Plus (Plus returns Compare>=0)
inline int Compare(const LatticeWeight& w1, const LatticeWeight& w2) {
    (void)w1; (void)w2;
    return 0;
}

// TODO: implement Plus — selects pair with smaller total cost (value1+value2)
inline LatticeWeight Plus(const LatticeWeight& w1, const LatticeWeight& w2) {
    (void)w2;
    return w1;
}

// TODO: implement Times — pointwise addition
inline LatticeWeight Times(const LatticeWeight& w1, const LatticeWeight& w2) {
    (void)w1; (void)w2;
    return LatticeWeight::Zero();
}

// TODO: implement Divide — pointwise subtraction with validity checks
inline LatticeWeight Divide(const LatticeWeight& w1, const LatticeWeight& w2,
                            DivideType) {
    (void)w1; (void)w2;
    return LatticeWeight::Zero();
}

// TODO: implement ApproxEqual
inline bool ApproxEqual(const LatticeWeight& w1, const LatticeWeight& w2,
                        float delta) {
    (void)w1; (void)w2; (void)delta;
    return false;
}

inline bool operator==(const LatticeWeight& a, const LatticeWeight& b) {
    volatile float va1 = a.Value1(), va2 = a.Value2();
    volatile float vb1 = b.Value1(), vb2 = b.Value2();
    return va1 == vb1 && va2 == vb2;
}
inline bool operator!=(const LatticeWeight& a, const LatticeWeight& b) {
    return !(a == b);
}

// TODO: implement text output — format "v1,v2" using WriteFloatType
inline std::ostream& operator<<(std::ostream& os, const LatticeWeight& w) {
    (void)w;
    return os;
}

// TODO: implement text input — parse "v1,v2" using ReadFloatType
inline std::istream& operator>>(std::istream& is, LatticeWeight& w) {
    (void)w;
    return is;
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

    // TODO: implement
    CompactLatticeWeight Quantize(float delta = kDelta) const {
        (void)delta;
        return *this;
    }

    // TODO: implement — reverses the string order, keeps weight
    CompactLatticeWeight Reverse() const {
        return *this;
    }

    // TODO: implement binary I/O
    std::ostream& Write(std::ostream& os) const { return os; }
    std::istream& Read(std::istream& is) { return is; }

 private:
    LatticeWeight weight_;
    std::vector<int32_t> string_;
};

// TODO: implement Compare for CompactLatticeWeight
inline int Compare(const CompactLatticeWeight& w1,
                   const CompactLatticeWeight& w2) {
    (void)w1; (void)w2;
    return 0;
}

// TODO: implement Plus
inline CompactLatticeWeight Plus(const CompactLatticeWeight& w1,
                                 const CompactLatticeWeight& w2) {
    (void)w2;
    return w1;
}

// TODO: implement Times — combine weights, concatenate strings
inline CompactLatticeWeight Times(const CompactLatticeWeight& w1,
                                  const CompactLatticeWeight& w2) {
    (void)w1; (void)w2;
    return CompactLatticeWeight::Zero();
}

// TODO: implement Divide — DIVIDE_LEFT removes prefix, DIVIDE_RIGHT removes suffix
inline CompactLatticeWeight Divide(const CompactLatticeWeight& w1,
                                   const CompactLatticeWeight& w2,
                                   DivideType dt) {
    (void)w1; (void)w2; (void)dt;
    return CompactLatticeWeight::Zero();
}

// TODO: implement
inline bool ApproxEqual(const CompactLatticeWeight& w1,
                        const CompactLatticeWeight& w2, float delta) {
    (void)w1; (void)w2; (void)delta;
    return false;
}

inline bool operator==(const CompactLatticeWeight& a,
                       const CompactLatticeWeight& b) {
    return a.Weight() == b.Weight() && a.String() == b.String();
}
inline bool operator!=(const CompactLatticeWeight& a,
                       const CompactLatticeWeight& b) {
    return !(a == b);
}

// TODO: implement text output — format "v1,v2,s1_s2_..."
inline std::ostream& operator<<(std::ostream& os,
                                const CompactLatticeWeight& w) {
    (void)w;
    return os;
}

// TODO: implement text input — parse "v1,v2,s1_s2_..."
inline std::istream& operator>>(std::istream& is, CompactLatticeWeight& w) {
    (void)w;
    return is;
}

// ======================================================================
// CompactLatticeWeightCommonDivisor
// ======================================================================

struct CompactLatticeWeightCommonDivisor {
    // TODO: implement — weight = Plus(w1,w2), string = longest common prefix
    CompactLatticeWeight operator()(const CompactLatticeWeight& w1,
                                    const CompactLatticeWeight& w2) const {
        (void)w1; (void)w2;
        return CompactLatticeWeight::Zero();
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

    // TODO: implement — return interned string of parent with i appended
    const Entry* Successor(const Entry* parent, IntType i) {
        (void)parent; (void)i;
        return nullptr;
    }

    // TODO: implement
    const Entry* Concatenate(const Entry* a, const Entry* b) {
        (void)a; (void)b;
        return nullptr;
    }

    // TODO: implement
    const Entry* CommonPrefix(const Entry* a, const Entry* b) {
        (void)a; (void)b;
        return nullptr;
    }

    // TODO: implement — truncate vector b to common prefix with Entry a
    void ReduceToCommonPrefix(const Entry* a, std::vector<IntType>* b) {
        (void)a; (void)b;
    }

    // TODO: implement — remove first n elements from string a
    const Entry* RemovePrefix(const Entry* a, size_t n) {
        (void)a; (void)n;
        return nullptr;
    }

    // TODO: implement — check if a is a prefix of b (using pointer traversal)
    bool IsPrefixOf(const Entry* a, const Entry* b) const {
        (void)a; (void)b;
        return false;
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

    // TODO: implement
    const Entry* ConvertFromVector(const std::vector<IntType>& vec) {
        (void)vec;
        return nullptr;
    }

    LatticeStringRepository() { new_entry_ = new Entry; }

    void Destroy() {
        for (auto iter = set_.begin(); iter != set_.end(); ++iter)
            delete *iter;
        SetType tmp;
        tmp.swap(set_);
        if (new_entry_) { delete new_entry_; new_entry_ = nullptr; }
    }

    // TODO: implement — keep only entries reachable from to_keep, delete rest
    void Rebuild(const std::vector<const Entry*>& to_keep) {
        (void)to_keep;
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

    LatticeStringRepository(const LatticeStringRepository&) = delete;
    LatticeStringRepository& operator=(const LatticeStringRepository&) = delete;

    Entry* new_entry_;
    SetType set_;
};

#endif  // LATTICE_WEIGHT_H_
