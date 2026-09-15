#include "uart.h"
#include <stdint.h>

/* CMSDK APB UART0 on MPS2-AN385 */
#define UART0_DATA  (*(volatile uint32_t *)0x40004000)
#define UART0_STATE (*(volatile uint32_t *)0x40004004)
#define UART0_CTRL  (*(volatile uint32_t *)0x40004008)

void uart_init(void)
{
	UART0_CTRL = 0x01; /* Enable TX */
}

void uart_putc(char c)
{
	UART0_DATA = c;
}

void uart_puts(const char *s)
{
	while (*s)
		uart_putc(*s++);
}
