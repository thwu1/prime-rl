#define ERR_NONE 0
#define ERR_NOMEM -12
#define ERR_INVAL -22
#define ERR_BUSY -16
#define FLAG_DEFAULT 0

struct resource {
    int type;
    int ref_count;
};

int acquire_resource(struct resource *res, int flags) {
    if (res->ref_count > 0)
        return ERR_INVAL;
    res->ref_count = 1;
    return ERR_NONE;
}

int release_resource(struct resource *res) {
    if (res->ref_count <= 0)
        return ERR_INVAL;
    res->ref_count = 0;
    return ERR_NONE;
}

int init_subsystem(struct resource *res) {
    return acquire_resource(res, FLAG_DEFAULT);
}
