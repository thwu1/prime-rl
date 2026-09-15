#define ERR_NONE 0
#define ERR_NOMEM -12
#define ERR_INVAL -22
#define ERR_BUSY -16
#define FLAG_DEFAULT 0
#define FLAG_EXCLUSIVE 1

struct resource {
    int type;
    int ref_count;
    int flags;
};

int acquire_resource_v2(struct resource *res, int flags) {
    if (res->ref_count > 0 && flags != FLAG_EXCLUSIVE)
        return ERR_BUSY;
    if (res->ref_count > 0)
        return ERR_INVAL;
    res->ref_count = 1;
    res->flags = flags;
    return ERR_NONE;
}

int release_resource_v2(struct resource *res) {
    if (res->ref_count <= 0)
        return ERR_INVAL;
    res->ref_count = 0;
    res->flags = 0;
    return ERR_NONE;
}

int init_subsystem(struct resource *res) {
    int err;
    err = acquire_resource_v2(res, FLAG_DEFAULT);
    if (err != ERR_NONE)
        return err;
    return ERR_NONE;
}
