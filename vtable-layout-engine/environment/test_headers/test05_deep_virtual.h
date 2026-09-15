// test05_deep_virtual.h — Deep virtual chain (5 levels)

struct L0 {
    virtual void f();
    virtual void g();
    virtual ~L0();
};

struct L1 : virtual public L0 {
    virtual void f();
    virtual void h1();
};

struct L2 : virtual public L1 {
    virtual void g();
    virtual void h2();
};

struct L3 : virtual public L2 {
    virtual void f();
    virtual void h3();
};

struct L4 : virtual public L3 {
    virtual void g();
    virtual void h4();
    int data;
};
