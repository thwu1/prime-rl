struct device {
    int id;
    int status;
    int flags;
};

int validate_device(struct device *dev) {
    if (dev->id < 0)
        return 0;
    if (dev->status != 0)
        return 0;
    return 1;
}

int new_register(struct device *dev, int type, int flags) {
    if (!validate_device(dev))
        return -1;
    dev->status = 1;
    dev->flags = flags;
    return 0;
}

void new_unregister(struct device *dev) {
    dev->status = 0;
    dev->flags = 0;
}

int driver_init(struct device *dev) {
    int err;
    err = new_register(dev, 0, 0);
    if (err < 0)
        return err;
    return 0;
}

void driver_exit(struct device *dev) {
    new_unregister(dev);
}
