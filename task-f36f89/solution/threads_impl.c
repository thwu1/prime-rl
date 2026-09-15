/*
 * Preemptive threading implementation for ARM Cortex-M3.
 * PendSV-based context switching with SysTick-driven scheduling.
 * Stack allocation via K&R malloc.
 */
#include <stdint.h>
#include "threads.h"
#include "reg.h"
#include "malloc.h"

#define THREAD_PSP 0xFFFFFFFD

/* Thread Control Block */
typedef struct {
	void *stack;       /* current saved stack pointer */
	void *orig_stack;  /* original malloc'd base */
	uint8_t in_use;
} tcb_t;

static tcb_t tasks[MAX_TASKS];
static int lastTask;

void thread_self_terminal(void);

/*
 * Round-robin scheduler — called from PendSV handler.
 *
 * Saves old_sp into the outgoing task's TCB, then finds the next
 * in_use task (round-robin) and returns its saved stack pointer.
 *
 * This is a normal C function (not naked), called from the naked
 * PendSV stub via 'bl'.  AAPCS: old_sp in r0, return in r0.
 */
void *schedule(void *old_sp)
{
	tasks[lastTask].stack = old_sp;

	while (1) {
		lastTask++;
		if (lastTask == MAX_TASKS)
			lastTask = 0;
		if (tasks[lastTask].in_use)
			return tasks[lastTask].stack;
	}
}

/*
 * PendSV handler — performs the actual context switch.
 *
 * MUST be __attribute__((naked)) with ONLY inline assembly.
 * Mixing C statements in a naked function is undefined behaviour
 * in GCC and causes register corruption (especially r7 frame
 * pointer on Thumb).
 *
 * The scheduling logic is delegated to the schedule() C function
 * via 'bl'.  AAPCS guarantees r0 holds the return value.
 */
void __attribute__((naked)) pendsv_handler(void)
{
	__asm volatile(
		"mrs   r0, psp\n"
		"stmdb r0!, {r4-r11, lr}\n"  /* save sw context + EXC_RETURN */
		"bl    schedule\n"            /* r0 = old_sp -> r0 = new_sp  */
		"ldmia r0!, {r4-r11, lr}\n"  /* restore next task's context  */
		"msr   psp, r0\n"
		"bx    lr\n"                  /* exception return             */
	);
}

/*
 * SysTick handler — pends PendSV so the context switch happens
 * at the lowest exception priority, avoiding priority-inversion
 * issues with other interrupts.
 */
void systick_handler(void)
{
	SCB_ICSR |= SCB_ICSR_PENDSVSET;
}

/*
 * Create a thread.
 *
 * Allocates a stack via malloc and initialises the 17-word frame
 * that PendSV / thread_start expects:
 *
 *  offset  content
 *  ------  ---------------------------------
 *  [0-7]   r4-r11        (software-saved)
 *  [8]     LR/EXC_RETURN (0xFFFFFFFD = thread mode, PSP)
 *  [9]     r0            (= arg, hardware-saved)
 *  [10-12] r1, r2, r3
 *  [13]    r12
 *  [14]    LR            (= thread_self_terminal)
 *  [15]    PC            (= func entry point)
 *  [16]    xPSR          (= 0x01000000, Thumb bit)
 */
int thread_create(void (*func)(void *), void *arg)
{
	int id;
	uint32_t *stack;

	for (id = 0; id < MAX_TASKS; id++) {
		if (!tasks[id].in_use)
			break;
	}
	if (id == MAX_TASKS)
		return -1;

	stack = (uint32_t *)malloc(STACK_SIZE * sizeof(uint32_t));
	if (!stack)
		return -1;
	tasks[id].orig_stack = stack;

	stack += STACK_SIZE - 17;
	stack[8]  = (uint32_t)THREAD_PSP;
	stack[9]  = (uint32_t)arg;
	stack[14] = (uint32_t)&thread_self_terminal;
	stack[15] = (uint32_t)func;
	stack[16] = (uint32_t)0x01000000;   /* xPSR Thumb bit */

	tasks[id].stack  = stack;
	tasks[id].in_use = 1;
	return id;
}

void thread_kill(int thread_id)
{
	tasks[thread_id].in_use = 0;
	free(tasks[thread_id].orig_stack);
}

/*
 * Called when a thread function returns.
 *
 * Disables interrupts to safely remove the task from the scheduler.
 * Does NOT call thread_kill / free, because the thread is still
 * executing on its own stack — PendSV will write saved context to
 * it on the very next context switch.  Freeing the stack here would
 * corrupt the K&R free-list.  The 4 KB per dead thread is an
 * acceptable leak given the 32 KB heap.
 */
void thread_self_terminal(void)
{
	__asm volatile("cpsid i");
	tasks[lastTask].in_use = 0;
	__asm volatile("cpsie i");
	while (1);
}

/*
 * C helper for thread_start — configures PendSV priority, SysTick,
 * and returns the first thread's saved stack pointer.
 *
 * Separated from the naked thread_start so that MMIO writes and
 * variable access use normal C code with compiler-managed registers.
 */
void *thread_bootstrap(void)
{
	/* PendSV to lowest exception priority */
	SCB_SHPR3 |= 0x00FF0000u;

	/* SysTick: 10 ms period, CPU clock, interrupt enabled */
	SYSTICK_LOAD = (CPU_CLOCK_HZ / TICK_RATE_HZ) - 1u;
	SYSTICK_VAL  = 0;
	SYSTICK_CTRL = 0x07u;

	lastTask = 0;
	return tasks[0].stack;
}

/*
 * Bootstrap the threading system.
 *
 * Calls thread_bootstrap() to configure peripherals (via normal C),
 * then switches from MSP to PSP and manually pops the first task's
 * saved context to begin execution.
 *
 * naked because we manage the MSP->PSP transition and register
 * loading ourselves.
 *
 * Critical detail: after popping the software-saved context,
 * lr holds EXC_RETURN (0xFFFFFFFD) from stack[8].  We must
 * explicitly load lr from the hardware frame (stack[14] = offset
 * sp+20 after the pop) so that when the thread function returns,
 * it branches to thread_self_terminal — NOT to the EXC_RETURN
 * magic value, which would hard-fault in thread mode.
 */
void __attribute__((naked)) thread_start(void)
{
	__asm volatile(
		"bl    thread_bootstrap\n"   /* r0 = tasks[0].stack          */
		"msr   psp, r0\n"
		"mov   r0, #3\n"            /* CONTROL: PSP + unprivileged  */
		"msr   control, r0\n"
		"isb\n"
		"pop   {r4-r11, lr}\n"      /* pop sw context from PSP      */
		"ldr   lr, [sp, #20]\n"     /* lr = thread_self_terminal    */
		"ldr   r0, [sp]\n"          /* r0 = thread argument         */
		"ldr   pc, [sp, #24]\n"     /* jump to task entry point     */
	);
}
