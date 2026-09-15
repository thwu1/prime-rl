// test06_nearly_empty.h — Nearly-empty virtual base primary selection

struct Shareme {
    virtual void foo();
};

struct ABase : virtual Shareme {
    virtual void bar();
};

struct AnotherBase : virtual Shareme {
    virtual void baz();
};

struct Combined : virtual ABase, virtual AnotherBase {
    virtual void foo();
    virtual void qux();
};
