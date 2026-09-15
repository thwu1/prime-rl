#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "assembler.h"

static char *strip_comment_and_trim(char *s) {
    /* Remove comments (everything after ; or #) */
    for (char *c = s; *c; c++) {
        if (*c == ';' || *c == '#') { *c = '\0'; break; }
    }
    /* Trim leading whitespace */
    while (isspace((unsigned char)*s)) s++;
    /* Trim trailing whitespace */
    char *end = s + strlen(s);
    while (end > s && isspace((unsigned char)*(end - 1))) end--;
    *end = '\0';
    return s;
}

int parse_assembly(const char *source, Program *prog) {
    memset(prog, 0, sizeof(*prog));
    char *buf = strdup(source);
    if (!buf) return -1;

    char *saveptr = NULL;
    char *rawline = strtok_r(buf, "\n", &saveptr);
    int lineno = 0;

    while (rawline) {
        lineno++;
        char tmp[512];
        strncpy(tmp, rawline, sizeof(tmp) - 1);
        tmp[sizeof(tmp) - 1] = '\0';
        char *text = strip_comment_and_trim(tmp);

        if (!*text) {
            rawline = strtok_r(NULL, "\n", &saveptr);
            continue;
        }

        /* --- Label detection --- */
        char label_name[MAX_NAME_LEN] = "";
        if ((isalpha((unsigned char)*text) || *text == '_')) {
            char *colon = strchr(text, ':');
            if (colon) {
                int len = (int)(colon - text);
                if (len > 0 && len < MAX_NAME_LEN) {
                    memcpy(label_name, text, len);
                    label_name[len] = '\0';
                }
                text = strip_comment_and_trim(colon + 1);
            }
        }

        /* --- Statement parsing --- */
        if (*text) {
            char mnemonic[32] = "", operand[MAX_NAME_LEN] = "";
            sscanf(text, "%31s %63s", mnemonic, operand);
            for (int i = 0; mnemonic[i]; i++)
                mnemonic[i] = tolower((unsigned char)mnemonic[i]);

            Item *it = &prog->items[prog->num_items];
            memset(it, 0, sizeof(*it));
            it->line = lineno;

            if (strcmp(mnemonic, "inst") == 0) {
                it->type = ITEM_INST;
                it->fixed_size = atoi(operand);
                it->size = it->fixed_size;
            } else if (strcmp(mnemonic, "jmp") == 0 || strcmp(mnemonic, "jcc") == 0) {
                it->type = ITEM_JUMP;
                strncpy(it->target, operand, MAX_NAME_LEN - 1);
                it->is_cond = (strcmp(mnemonic, "jcc") == 0);
                it->relaxed = false;
                it->size = 2;
            } else if (strcmp(mnemonic, ".fill") == 0) {
                it->type = ITEM_FILL;
                it->fixed_size = atoi(operand);
                it->size = it->fixed_size;
            } else if (strcmp(mnemonic, ".align") == 0) {
                it->type = ITEM_ALIGN;
                it->alignment = atoi(operand);
                it->size = 0;
            } else {
                fprintf(stderr, "Error: unknown mnemonic '%s' at line %d\n",
                        mnemonic, lineno);
                free(buf);
                return -1;
            }
            prog->num_items++;
        }

        /* --- Register label (marks position in the item list) --- */
        if (label_name[0]) {
            if (prog->num_labels >= MAX_LABELS) {
                fprintf(stderr, "Error: too many labels\n");
                free(buf);
                return -1;
            }
            Label *lb = &prog->labels[prog->num_labels++];
            strncpy(lb->name, label_name, MAX_NAME_LEN - 1);
            lb->name[MAX_NAME_LEN - 1] = '\0';
            lb->item_index = prog->num_items;
            lb->offset = 0;
        }

        rawline = strtok_r(NULL, "\n", &saveptr);
    }

    free(buf);
    return 0;
}
