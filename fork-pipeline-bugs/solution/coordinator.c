/*
 * coordinator.c — Parallel computation coordinator (solution)
 *
 * Forks worker processes, distributes computation, collects results
 * via pipes and shared memory, cross-validates, and reports.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <sys/mman.h>
#include "compute.h"

typedef struct {
    int state;                    /* 0=PENDING, 1=RUNNING, 2=DONE */
    long partial_sum;
    unsigned long long checksum;
} worker_state_t;

typedef struct {
    worker_state_t workers[MAX_WORKERS];
} shared_state_t;

int main(int argc, char **argv)
{
    if (argc != 4) {
        fprintf(stderr, "Usage: %s <input> <output> <nworkers>\n", argv[0]);
        return 1;
    }

    const char *inpath   = argv[1];
    const char *outpath  = argv[2];
    int         nworkers = atoi(argv[3]);

    if (nworkers < 1 || nworkers > MAX_WORKERS) {
        fprintf(stderr, "nworkers must be 1..%d\n", MAX_WORKERS);
        return 1;
    }

    int count;
    int *numbers = read_numbers(inpath, &count);
    if (count == 0) {
        fprintf(stderr, "Empty input\n");
        return 1;
    }

    /* Shared memory for cross-process state tracking.
       MAP_SHARED is required so that child writes are visible to the parent.
       MAP_PRIVATE would create copy-on-write pages, siloing child updates. */
    shared_state_t *state = mmap(NULL, sizeof(shared_state_t),
                                  PROT_READ | PROT_WRITE,
                                  MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (state == MAP_FAILED) { perror("mmap"); return 1; }
    memset(state, 0, sizeof(shared_state_t));

    FILE *outf = fopen(outpath, "w");
    if (!outf) { perror("fopen output"); return 1; }

    fprintf(outf, "COORDINATOR workers=%d datasize=%d\n", nworkers, count);
    /* Must fflush before fork: file-backed stdio streams are fully buffered.
       Without this, the buffered header is copied into each child's address
       space and written to the file when the child exits. */
    fflush(outf);

    int pfd[2];
    if (pipe(pfd) < 0) { perror("pipe"); return 1; }

    int chunk_size = count / nworkers;
    pid_t cpids[MAX_WORKERS];

    for (int w = 0; w < nworkers; w++) {
        pid_t pid = fork();
        if (pid < 0) { perror("fork"); return 1; }

        if (pid == 0) {
            /* Child: close read end of pipe */
            close(pfd[0]);

            state->workers[w].state = 1;  /* RUNNING */

            int lo = w * chunk_size;
            int hi = (w == nworkers - 1) ? count : lo + chunk_size;

            long psum = compute_partial_sum(numbers, lo, hi);
            unsigned long long cksum = compute_checksum(numbers, lo, hi);

            /* Update shared memory */
            state->workers[w].partial_sum = psum;
            state->workers[w].checksum = cksum;
            state->workers[w].state = 2;  /* DONE */

            /* Send result through pipe */
            char msg[128];
            int mlen = snprintf(msg, sizeof(msg), "%d %ld %llu\n", w, psum, cksum);
            ssize_t wr = write(pfd[1], msg, mlen);
            (void)wr;
            close(pfd[1]);

            /* Must use _exit() to avoid flushing parent's inherited stdio
               buffers. exit() would run atexit handlers and flush all
               streams, causing the parent's buffered output to be written
               again by each child. */
            _exit(0);
        }

        cpids[w] = pid;
    }

    /* Parent: close write end so reads see EOF when all children close
       their copies. Without this, fgets blocks forever because the
       parent's open write reference prevents the pipe from signaling EOF. */
    close(pfd[1]);

    /* Read worker results from pipe */
    FILE *rpipe = fdopen(pfd[0], "r");
    if (!rpipe) { perror("fdopen"); return 1; }

    long pipe_sums[MAX_WORKERS];
    unsigned long long pipe_checksums[MAX_WORKERS];
    memset(pipe_sums, 0, sizeof(pipe_sums));
    memset(pipe_checksums, 0, sizeof(pipe_checksums));
    char linebuf[256];

    while (fgets(linebuf, sizeof(linebuf), rpipe)) {
        int wid;
        long ps;
        unsigned long long ck;
        if (sscanf(linebuf, "%d %ld %llu", &wid, &ps, &ck) == 3) {
            if (wid >= 0 && wid < nworkers) {
                pipe_sums[wid] = ps;
                pipe_checksums[wid] = ck;
            }
        }
    }
    fclose(rpipe);

    /* Reap all children to prevent zombies */
    for (int w = 0; w < nworkers; w++) {
        int st;
        waitpid(cpids[w], &st, 0);
    }

    /* Write per-worker results */
    long pipe_total = 0;
    for (int w = 0; w < nworkers; w++) {
        const char *sname = state->workers[w].state == 2 ? "DONE" :
                            state->workers[w].state == 1 ? "RUNNING" : "PENDING";
        fprintf(outf, "W%d: sum=%ld checksum=%llu state=%s\n",
                w, pipe_sums[w], pipe_checksums[w], sname);
        pipe_total += pipe_sums[w];
    }

    fprintf(outf, "TOTAL: %ld\n", pipe_total);

    /* Cross-validate checksums: pipe vs shared memory */
    int cksum_ok = 1;
    for (int w = 0; w < nworkers; w++) {
        if (pipe_checksums[w] != state->workers[w].checksum) {
            cksum_ok = 0;
            break;
        }
    }
    fprintf(outf, "CHECKSUM_VERIFY: %s\n", cksum_ok ? "OK" : "FAIL");

    /* Cross-validate sums: pipe total vs shared memory total */
    long shm_total = 0;
    for (int w = 0; w < nworkers; w++)
        shm_total += state->workers[w].partial_sum;
    fprintf(outf, "SUM_VERIFY: %s\n",
            (pipe_total > 0 && pipe_total == shm_total) ? "OK" : "FAIL");

    /* Progress */
    int done_count = 0;
    for (int w = 0; w < nworkers; w++)
        if (state->workers[w].state == 2)
            done_count++;
    fprintf(outf, "PROGRESS: %d/%d DONE\n", done_count, nworkers);

    fclose(outf);
    free(numbers);
    munmap(state, sizeof(shared_state_t));
    return 0;
}
