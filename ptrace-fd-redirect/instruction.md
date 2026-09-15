A build system and diagnostic reporter exist at `/app/`. Running `make` in `/app/` compiles `ptysession` and `reporter` from their source files. The reporter (`/app/reporter`) prints the calling process's session, terminal, and file descriptor properties as `key=value` pairs — examine `/app/reporter.c` to see which properties it reports.

The file `/app/ptysession.c` is a stub. Implement it as a fully functional PTY session manager.

**Interface:** `./ptysession <command> [args...]`

The tool must allocate a pseudoterminal pair, fork a child into a new session backed by the PTY slave, and provide bidirectional I/O forwarding between the parent's standard file descriptors and the PTY master using `poll(2)` or equivalent multiplexing.

**Required session properties** (verifiable via `./ptysession ./reporter`):

- Child is a session leader (SID == PID)
- Child heads its own process group (PGID == PID)
- Child has a controlling terminal (`/dev/tty` openable)
- Child stdin is a PTY slave device (`/dev/pts/*`)
- PTY foreground process group equals the child's PGID
- Child has exactly 3 open file descriptors (no leaked FDs from parent)
- PTY terminal dimensions are at least 24 rows and 80 columns

**Signal forwarding:**

- `SIGTERM` received by ptysession must be forwarded to the child's process group
- `SIGINT` received by ptysession must be forwarded to the child's process group
- After the child terminates due to a forwarded signal, ptysession exits with code `128 + signal_number`

**I/O and exit behavior:**

- All child output via the PTY slave is relayed to ptysession's stdout (including multiline output)
- Data written to ptysession's stdin (when connected to a pipe) is forwarded to the child through the PTY master
- The child's exit code propagates as ptysession's exit code (both zero and non-zero values)
- ptysession exits within 5 seconds after the child process terminates