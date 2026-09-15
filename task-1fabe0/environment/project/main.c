/*
 * main.c - Bare-metal kernel entry point for Raspberry Pi 4
 */

extern void uart_init(void);
extern void uart_puts(const char *s);

void main(void)
{
    uart_init();
    uart_puts("RPi4 bare metal boot OK\n");

    while (1) {
        /* Main loop — spin */
    }
}
