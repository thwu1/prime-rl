#ifndef ASSEMBLER_H
#define ASSEMBLER_H

#include <stdbool.h>

#define MAX_ITEMS 4096
#define MAX_LABELS 1024
#define MAX_NAME_LEN 64

typedef enum { ITEM_INST, ITEM_JUMP, ITEM_FILL, ITEM_ALIGN } ItemType;

typedef struct {
    ItemType type;
    int line;
    int offset;
    int size;
    char target[MAX_NAME_LEN];
    bool is_cond;
    bool relaxed;
    int fixed_size;
    int alignment;
} Item;

typedef struct {
    char name[MAX_NAME_LEN];
    int item_index;
    int offset;
} Label;

typedef struct {
    Item items[MAX_ITEMS];
    int num_items;
    Label labels[MAX_LABELS];
    int num_labels;
} Program;

typedef struct {
    int total_size;
    int iterations;
} LayoutResult;

int parse_assembly(const char *source, Program *prog);
void relax_layout(Program *prog, LayoutResult *result);
void print_json(const Program *prog, const LayoutResult *result);

#endif
