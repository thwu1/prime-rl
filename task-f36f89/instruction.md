A bare-metal ARM Cortex-M3 skeleton is provided at `/app/`. It targets the MPS2-AN385 board in QEMU and includes working boot code (`startup.c`), UART output (`uart.c`), a linker script (`os.ld`), register definitions (`reg.h`), and a test program (`os.c`) that uses a threading API declared in `threads.h`.

The test program creates four threads (three finite workers and one long-running sentinel) and calls `thread_start()`. Currently the build fails because the threading implementation does not exist.

Implement the full preemptive threading system:

- `thread_create(func, arg)` -- allocate a stack from a heap allocator you implement, initialize the ARM Cortex-M3 exception stack frame, return a thread ID.
- `thread_start()` -- configure the SysTick timer, set interrupt priorities, and bootstrap into the first thread. Does not return.
- `thread_kill(id)` -- deallocate a thread and its stack.
- A PendSV handler for context switching and a SysTick handler to trigger it.
- A heap allocator (`malloc`/`free`) for dynamic stack allocation.
- Thread self-termination: when a thread function returns, the thread must be cleaned up without crashing the system.

Do not modify `/app/os.c`, `/app/startup.c`, `/app/uart.c`, `/app/uart.h`, `/app/reg.h`, or `/app/threads.h`. Update the Makefile to compile your new source files. The vector table in `startup.c` uses weak aliases -- your handler symbols override them automatically.

Build with `make` in `/app/`. Test with `qemu-system-arm -M mps2-an385 -nographic -kernel /app/os.bin`. All four threads must produce interleaved output proving preemptive scheduling, workers must terminate cleanly, and the sentinel must continue running afterward.