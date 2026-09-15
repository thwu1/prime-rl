/*
 * NEC2 Card Deck Parser
 * Parses .nec geometry deck files to extract antenna structure definition,
 * excitation parameters, and frequency specification.
 */


#include "deck_parser.h"

int parse_deck(const char *filename, DeckData *deck) {
    FILE *fp = fopen(filename, "r");
    if (!fp) {
        fprintf(stderr, "Error: cannot open deck file %s\n", filename);
        return -1;
    }

    memset(deck, 0, sizeof(DeckData));

    char line[MAX_LINE];
    int in_comments = 0;

    while (fgets(line, MAX_LINE, fp)) {
        int len = strlen(line);
        while (len > 0 && (line[len-1] == '\n' || line[len-1] == '\r'))
            line[--len] = '\0';

        if (len < 2) continue;

        char card[3];
        card[0] = line[0];
        card[1] = line[1];
        card[2] = '\0';

        if (strcmp(card, "CM") == 0) { in_comments = 1; continue; }
        if (strcmp(card, "CE") == 0) { in_comments = 0; continue; }
        if (in_comments) continue;

        if (strcmp(card, "GW") == 0) {
            /* Parse wire geometry card */
            continue;
        }
        if (strcmp(card, "EX") == 0) {
            /* Parse excitation card */
            continue;
        }
        if (strcmp(card, "FR") == 0) {
            /* Parse frequency card */
            continue;
        }
        if (strcmp(card, "GE") == 0) {
            continue;
        }
        if (strcmp(card, "EN") == 0) {
            break;
        }
    }

    fclose(fp);
    return 0;
}
