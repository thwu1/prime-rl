struct Widget {
    int id;
    double value;
    char *label;
};

struct Panel {
    struct Widget primary;
    struct Widget secondary;
    int flags;
};

void widget_set_value(struct Widget *w) {
    w->value = 1.0;
}

void init_widget(struct Widget *w) {
    widget_set_value(w);
}

double read_widget_value(struct Widget *w) {
    return w->value;
}

double panel_primary_value(struct Panel *p) {
    return p->primary.value;
}

double *panel_value_ptr(struct Panel *p) {
    return &p->primary.value;
}

char **panel_label_ptr(struct Panel *p) {
    return &p->primary.label;
}
