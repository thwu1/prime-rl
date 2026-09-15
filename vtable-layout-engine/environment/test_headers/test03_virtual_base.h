// test03_virtual_base.h — Virtual inheritance basics

struct V {
    virtual void f();
    virtual ~V();
};

struct B : virtual public V {
    virtual void g();
};

struct C : virtual public V {
    virtual void h();
};

struct D : public B, public C {
    virtual void f();
};
