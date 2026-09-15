/*
 * converter.c — Import COCO benchmark TSV data into a SQLite database.
 *
 * Reads tab-separated run data for each algorithm and populates
 * the benchmark.db database with runs and targets_reached tables.
 *
 * Usage: ./converter <metadata.json> <data_dir> <output.db>
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sqlite3.h>
#include <math.h>

#define MAX_LINE 4096
#define MAX_ALGOS 16
#define MAX_ALGO_NAME 64

/* Simple JSON parser for metadata — extracts algorithm names */
static int parse_algorithms(const char *meta_path, char algos[][MAX_ALGO_NAME],
                            int *n_algos) {
    FILE *fp = fopen(meta_path, "r");
    if (!fp) {
        fprintf(stderr, "Cannot open metadata: %s\n", meta_path);
        return -1;
    }

    char buf[MAX_LINE];
    int in_algos = 0;
    *n_algos = 0;

    while (fgets(buf, sizeof(buf), fp)) {
        if (strstr(buf, "\"algorithms\"")) {
            in_algos = 1;
            continue;
        }
        if (in_algos) {
            if (strchr(buf, ']')) {
                in_algos = 0;
                continue;
            }
            char *q1 = strchr(buf, '"');
            if (q1) {
                char *q2 = strchr(q1 + 1, '"');
                if (q2 && *n_algos < MAX_ALGOS) {
                    int len = (int)(q2 - q1 - 1);
                    strncpy(algos[*n_algos], q1 + 1, len);
                    algos[*n_algos][len] = '\0';
                    (*n_algos)++;
                }
            }
        }
    }
    fclose(fp);
    return 0;
}

static int create_schema(sqlite3 *db) {
    const char *sql =
        "CREATE TABLE IF NOT EXISTS runs ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  algorithm TEXT NOT NULL,"
        "  function_id INTEGER NOT NULL,"
        "  dimension INTEGER NOT NULL,"
        "  instance INTEGER NOT NULL,"
        "  budget INTEGER NOT NULL,"
        "  UNIQUE(algorithm, function_id, dimension, instance)"
        ");"
        "CREATE TABLE IF NOT EXISTS targets_reached ("
        "  run_id INTEGER NOT NULL REFERENCES runs(id),"
        "  target TEXT NOT NULL,"
        "  evals INTEGER NOT NULL,"
        "  PRIMARY KEY (run_id, target)"
        ");";

    char *err = NULL;
    if (sqlite3_exec(db, sql, NULL, NULL, &err) != SQLITE_OK) {
        fprintf(stderr, "Schema error: %s\n", err);
        sqlite3_free(err);
        return -1;
    }
    return 0;
}

static int import_tsv(sqlite3 *db, const char *data_dir, const char *algo) {
    char path[1024];
    snprintf(path, sizeof(path), "%s/%s.tsv", data_dir, algo);

    FILE *fp = fopen(path, "r");
    if (!fp) {
        fprintf(stderr, "Cannot open TSV: %s\n", path);
        return -1;
    }

    sqlite3_stmt *ins_run = NULL;
    sqlite3_stmt *ins_target = NULL;
    sqlite3_stmt *find_run = NULL;

    sqlite3_prepare_v2(db,
        "INSERT OR IGNORE INTO runs (algorithm, function_id, dimension, instance, budget) "
        "VALUES (?, ?, ?, ?, ?)",
        -1, &ins_run, NULL);

    sqlite3_prepare_v2(db,
        "SELECT id FROM runs WHERE algorithm = ? AND function_id = ? "
        "AND dimension = ? AND instance = ?",
        -1, &find_run, NULL);

    sqlite3_prepare_v2(db,
        "INSERT INTO targets_reached (run_id, target, evals) VALUES (?, ?, ?)",
        -1, &ins_target, NULL);

    char line[MAX_LINE];
    int rows_imported = 0;

    while (fgets(line, sizeof(line), fp)) {
        if (line[0] == '#' || line[0] == '\n' || line[0] == '\r')
            continue;

        /* Parse TSV: func_id, dim, instance, budget, target, evals */
        int func_id, dim, instance, budget, evals;
        char target[64];

        char *tok = strtok(line, "\t");
        if (!tok) continue;
        func_id = atoi(tok);

        tok = strtok(NULL, "\t");
        if (!tok) continue;
        dim = atoi(tok);

        tok = strtok(NULL, "\t");
        if (!tok) continue;
        instance = atoi(tok);

        tok = strtok(NULL, "\t");
        if (!tok) continue;
        budget = (int)round(strtod(tok, NULL));

        tok = strtok(NULL, "\t");
        if (!tok) continue;
        strncpy(target, tok, sizeof(target) - 1);
        target[sizeof(target) - 1] = '\0';
        char *nl = strchr(target, '\n');
        if (nl) *nl = '\0';
        nl = strchr(target, '\r');
        if (nl) *nl = '\0';

        tok = strtok(NULL, "\t\n\r");
        if (!tok) continue;
        evals = atoi(tok);

        /* Insert run record (algorithm, function_id, dimension, instance, budget) */
        sqlite3_reset(ins_run);
        sqlite3_bind_text(ins_run, 1, algo, -1, SQLITE_STATIC);
        sqlite3_bind_int(ins_run, 2, func_id);
        sqlite3_bind_int(ins_run, 3, instance);
        sqlite3_bind_int(ins_run, 4, dim);
        sqlite3_bind_int(ins_run, 5, budget);
        sqlite3_step(ins_run);

        /* Find the run ID for inserting target data */
        sqlite3_reset(find_run);
        sqlite3_bind_text(find_run, 1, algo, -1, SQLITE_STATIC);
        sqlite3_bind_int(find_run, 2, func_id);
        sqlite3_bind_int(find_run, 3, instance);
        sqlite3_bind_int(find_run, 4, dim);

        int run_id = -1;
        if (sqlite3_step(find_run) == SQLITE_ROW) {
            run_id = sqlite3_column_int(find_run, 0);
        }

        if (run_id >= 0) {
            sqlite3_reset(ins_target);
            sqlite3_bind_int(ins_target, 1, run_id);
            sqlite3_bind_text(ins_target, 2, target, -1, SQLITE_STATIC);
            sqlite3_bind_int(ins_target, 3, evals);
            sqlite3_step(ins_target);
            rows_imported++;
        }
    }

    sqlite3_finalize(ins_run);
    sqlite3_finalize(find_run);
    sqlite3_finalize(ins_target);
    fclose(fp);

    printf("  %s: %d target rows imported\n", algo, rows_imported);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "Usage: %s <metadata.json> <data_dir> <output.db>\n",
                argv[0]);
        return 1;
    }

    const char *meta_path = argv[1];
    const char *data_dir = argv[2];
    const char *db_path = argv[3];

    char algos[MAX_ALGOS][MAX_ALGO_NAME];
    int n_algos = 0;
    if (parse_algorithms(meta_path, algos, &n_algos) != 0)
        return 1;

    printf("Found %d algorithms in metadata\n", n_algos);

    sqlite3 *db = NULL;
    if (sqlite3_open(db_path, &db) != SQLITE_OK) {
        fprintf(stderr, "Cannot open database: %s\n", sqlite3_errmsg(db));
        return 1;
    }

    sqlite3_exec(db, "PRAGMA journal_mode=WAL;", NULL, NULL, NULL);

    if (create_schema(db) != 0) {
        sqlite3_close(db);
        return 1;
    }

    sqlite3_exec(db, "BEGIN TRANSACTION;", NULL, NULL, NULL);

    for (int i = 0; i < n_algos; i++) {
        if (import_tsv(db, data_dir, algos[i]) != 0) {
            sqlite3_exec(db, "ROLLBACK;", NULL, NULL, NULL);
            sqlite3_close(db);
            return 1;
        }
    }

    sqlite3_exec(db, "COMMIT;", NULL, NULL, NULL);
    sqlite3_close(db);

    printf("Database written to %s\n", db_path);
    return 0;
}
