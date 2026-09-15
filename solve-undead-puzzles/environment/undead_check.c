/*
 * undead_check.c — Validator for Undead puzzle solutions.
 *
 * Reads XOR-encrypted puzzle data from /app/puzzles.bin.
 * Validates solution files against decrypted puzzle constraints.
 *
 * Usage: undead-check <puzzle_id> <solution_file>
 * Exit 0 = valid, 1 = invalid, 2 = usage/data error.
 *
 * All format-revealing strings are obfuscated to prevent trivial
 * discovery via strings(1).
 */


#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define MAX_DIM 16
#define BIN_PATH "/app/puzzles.bin"
#define SEED_LEN 16

/*
 * Key derivation: LCG-based XOR mixing with file header seed.
 *
 * state = puzzle_id * 0x9E3779B1 (Knuth multiplicative hash)
 * for each byte i:
 *   state = state * 1103515245 + 12345   (glibc LCG)
 *   key[i] = seed[i % 16] ^ ((state >> 16) & 0xFF)
 */
static void derive_key(const uint8_t *seed, uint32_t pid,
                       uint8_t *key, int klen)
{
    uint32_t s = pid * 2654435761u;
    for (int i = 0; i < klen; i++) {
        s = s * 1103515245u + 12345u;
        key[i] = seed[i % SEED_LEN] ^ ((s >> 16) & 0xFF);
    }
}

static void xor_decrypt(uint8_t *data, const uint8_t *key, int len)
{
    for (int i = 0; i < len; i++)
        data[i] ^= key[i];
}

/*
 * Obfuscated header check — avoids placing "UNDEAD v1" as a
 * string literal in the binary.  Header chars stored as int array.
 */
static int check_header(const char *line, int expected_id)
{
    /* 'U','N','D','E','A','D',' ','v','1',' ' */
    static const int hc[] = {85, 78, 68, 69, 65, 68, 32, 118, 49, 32, 0};
    int i;
    for (i = 0; hc[i]; i++) {
        if (line[i] != (char)hc[i])
            return 0;
    }
    int sol_id = atoi(line + i);
    return sol_id == expected_id;
}

static int count_visible(char grid[][MAX_DIM], int n,
                         int sr, int sc, int dr, int dc)
{
    int visible = 0;
    int reflected = 0;
    int r = sr, c = sc;

    while (r >= 0 && r < n && c >= 0 && c < n) {
        char cell = grid[r][c];
        if (cell == '/') {
            int nr = -dc, nc = -dr;
            dr = nr; dc = nc;
            reflected = 1;
        } else if (cell == '\\') {
            int nr = dc, nc = dr;
            dr = nr; dc = nc;
            reflected = 1;
        } else if (cell == 'Z') {
            visible++;
        } else if (cell == 'V' && !reflected) {
            visible++;
        } else if (cell == 'G' && reflected) {
            visible++;
        }
        r += dr;
        c += dc;
    }
    return visible;
}

int main(int argc, char *argv[])
{
    if (argc != 3)
        return 2;

    int target_id = atoi(argv[1]);
    const char *sol_path = argv[2];

    /* ---- Read and decrypt puzzle data ---- */

    FILE *bf = fopen(BIN_PATH, "rb");
    if (!bf) return 2;

    char magic[4];
    uint32_t version, count;
    uint8_t seed[SEED_LEN];

    if (fread(magic, 1, 4, bf) != 4 ||
        memcmp(magic, "UNDD", 4) != 0) {
        fclose(bf);
        return 2;
    }
    if (fread(&version, 4, 1, bf) != 1 || version != 2) {
        fclose(bf);
        return 2;
    }
    if (fread(&count, 4, 1, bf) != 1) { fclose(bf); return 2; }
    if (fread(seed, 1, SEED_LEN, bf) != SEED_LEN) { fclose(bf); return 2; }

    int found = 0;
    uint32_t dim = 0, nv = 0, ng = 0, nz = 0;
    char grid_mirrors[MAX_DIM][MAX_DIM];
    int top[MAX_DIM], bot[MAX_DIM], lft[MAX_DIM], rgt[MAX_DIM];
    memset(grid_mirrors, '.', sizeof(grid_mirrors));

    for (uint32_t p = 0; p < count; p++) {
        uint32_t pid, blen;
        if (fread(&pid, 4, 1, bf) != 1) break;
        if (fread(&blen, 4, 1, bf) != 1) break;

        if ((int)pid == target_id) {
            uint8_t *block = (uint8_t *)malloc(blen);
            if (!block || fread(block, 1, blen, bf) != blen) {
                free(block);
                fclose(bf);
                return 2;
            }

            uint8_t *key = (uint8_t *)malloc(blen);
            if (!key) { free(block); fclose(bf); return 2; }
            derive_key(seed, pid, key, blen);
            xor_decrypt(block, key, blen);
            free(key);

            /* Parse decrypted block */
            uint32_t *hdr = (uint32_t *)block;
            dim = hdr[0];
            nv  = hdr[1];
            ng  = hdr[2];
            nz  = hdr[3];
            uint32_t nm = hdr[4];

            if (dim > MAX_DIM) { free(block); fclose(bf); return 2; }

            uint8_t *mptr = block + 20;
            for (uint32_t m = 0; m < nm; m++) {
                uint8_t row = mptr[0], col = mptr[1], mtype = mptr[2];
                if (row < dim && col < dim)
                    grid_mirrors[row][col] = (mtype == 0) ? '/' : '\\';
                mptr += 4;
            }

            uint32_t *cptr = (uint32_t *)mptr;
            for (uint32_t i = 0; i < dim; i++) {
                top[i] = cptr[0];
                bot[i] = cptr[1];
                lft[i] = cptr[2];
                rgt[i] = cptr[3];
                cptr += 4;
            }

            free(block);
            found = 1;
            break;
        } else {
            fseek(bf, blen, SEEK_CUR);
        }
    }

    fclose(bf);
    if (!found) return 2;

    /* ---- Read and validate solution ---- */

    FILE *sf = fopen(sol_path, "r");
    if (!sf) return 2;

    char line[256];
    if (!fgets(line, sizeof(line), sf)) {
        fclose(sf);
        return 1;
    }

    /* Strip trailing newline/carriage-return */
    size_t len = strlen(line);
    while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r'))
        line[--len] = '\0';

    if (!check_header(line, target_id)) {
        fclose(sf);
        return 1;
    }

    char grid[MAX_DIM][MAX_DIM];
    for (uint32_t r = 0; r < dim; r++) {
        if (!fgets(line, sizeof(line), sf)) {
            fclose(sf);
            return 1;
        }
        len = strlen(line);
        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r'))
            line[--len] = '\0';

        if (len != dim) {
            fclose(sf);
            return 1;
        }
        for (uint32_t c = 0; c < dim; c++)
            grid[r][c] = line[c];
    }
    fclose(sf);

    /* Validate mirror positions */
    for (uint32_t r = 0; r < dim; r++)
        for (uint32_t c = 0; c < dim; c++)
            if (grid_mirrors[r][c] != '.' &&
                grid[r][c] != grid_mirrors[r][c])
                return 1;

    /* Validate monster counts */
    int vc = 0, gc = 0, zc = 0;
    for (uint32_t r = 0; r < dim; r++) {
        for (uint32_t c = 0; c < dim; c++) {
            if (grid_mirrors[r][c] != '.') continue;
            char ch = grid[r][c];
            if (ch == 'V') vc++;
            else if (ch == 'G') gc++;
            else if (ch == 'Z') zc++;
            else return 1;
        }
    }

    if ((uint32_t)vc != nv || (uint32_t)gc != ng || (uint32_t)zc != nz)
        return 1;

    /* Validate all 4N sight-line clues */
    for (uint32_t c = 0; c < dim; c++)
        if (count_visible(grid, dim, 0, c, 1, 0) != top[c])
            return 1;
    for (uint32_t c = 0; c < dim; c++)
        if (count_visible(grid, dim, dim - 1, c, -1, 0) != bot[c])
            return 1;
    for (uint32_t r = 0; r < dim; r++)
        if (count_visible(grid, dim, r, 0, 0, 1) != lft[r])
            return 1;
    for (uint32_t r = 0; r < dim; r++)
        if (count_visible(grid, dim, r, dim - 1, 0, -1) != rgt[r])
            return 1;

    return 0;
}
