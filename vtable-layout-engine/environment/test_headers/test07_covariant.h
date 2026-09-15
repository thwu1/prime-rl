// test07_covariant.h — Covariant returns through virtual bases

struct RetBase {
    int rb;
    virtual ~RetBase();
};

struct RetDerived : public RetBase {
    int rd;
};

struct CovarBase {
    virtual RetBase* make();
    virtual void other();
    virtual ~CovarBase();
};

struct CovarMid : virtual public CovarBase {
    virtual RetBase* make();
    virtual void mid_func();
};

struct CovarLeaf : public CovarMid {
    virtual RetDerived* make();
    virtual void leaf_func();
};
