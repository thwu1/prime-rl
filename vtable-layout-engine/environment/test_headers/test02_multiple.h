// test02_multiple.h — Multiple non-virtual inheritance with overrides

struct A {
    virtual void f();
    virtual ~A();
};

struct X {
    virtual void u();
    virtual ~X();
};

struct E : public X, public A {
    virtual void f();
};
