// test04_diamond_data.h — Diamond with data members affecting offsets

struct Root {
    virtual void f();
    virtual ~Root();
    int root_data;
};

struct Left : virtual public Root {
    virtual void g();
    int left_data;
};

struct Right : virtual public Root {
    virtual void h();
    double right_data;
};

struct Bottom : public Left, public Right {
    virtual void f();
    virtual void i();
    int bottom_data;
};
