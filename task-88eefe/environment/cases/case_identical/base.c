struct device {
    int id;
    int status;
};

int old_register(struct device *dev, int type) {
    dev->status = 1;
    return 0;
}

void old_unregister(struct device *dev) {
    dev->status = 0;
}

int driver_init(struct device *dev) {
    int err;
    err = old_register(dev, 0);
    return err;
}

void driver_exit(struct device *dev) {
    old_unregister(dev);
}
