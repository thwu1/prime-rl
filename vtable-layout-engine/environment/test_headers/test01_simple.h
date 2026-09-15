// test01_simple.h — Single inheritance with override

struct Base {
    virtual void foo();
    virtual void bar();
    virtual ~Base();
};

struct Derived : public Base {
    virtual void foo();
    virtual void baz();
};
