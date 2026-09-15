#include "uart.h"
#include "threads.h"

void worker(void *arg)
{
	const char *id = (const char *)arg;
	int i;
	for (i = 0; i < 5; i++) {
		uart_puts(id);
		uart_puts(": running\r\n");
		volatile int d;
		for (d = 0; d < 50000; d++);
	}
	/* Thread returns naturally after 5 iterations */
}

void sentinel(void *arg)
{
	(void)arg;
	while (1) {
		uart_puts("sentinel: alive\r\n");
		volatile int d;
		for (d = 0; d < 50000; d++);
	}
}

int main(void)
{
	uart_init();
	uart_puts("BOOT\r\n");

	thread_create(worker, "W1");
	thread_create(worker, "W2");
	thread_create(worker, "W3");
	thread_create(sentinel, (void *)0);

	thread_start();

	/* Should never reach here */
	return 0;
}
