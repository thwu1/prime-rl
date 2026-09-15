/*
 * uart.c - Mini UART (UART1) driver for Raspberry Pi 4
 *
 * Configures the BCM2711 auxiliary Mini UART on GPIO pins 14 (TXD)
 * and 15 (RXD) using ALT5 function.
 */

#include "mmio.h"

void uart_init(void)
{
    /* Enable the Mini UART (AUX peripheral bit 0) */
    mmio_write(AUX_ENABLES, 1);

    /* Disable TX/RX during configuration */
    mmio_write(AUX_MU_CNTL, 0);

    /* Disable receive and transmit interrupts */
    mmio_write(AUX_MU_IER, 0);

    /* Set data format to 8-bit mode */
    mmio_write(AUX_MU_LCR, 3);

    /* Set RTS line high (MCR = 0) */
    mmio_write(AUX_MU_MCR, 0);

    /* Set baud rate divisor */
    mmio_write(AUX_MU_BAUD, AUX_MU_BAUD_VAL);

    /*
     * Configure GPIO pins 14 and 15 for Mini UART (ALT5).
     *
     * GPFSEL1 controls pins 10-19.
     * Pin 14 function select: bits [14:12]
     * Pin 15 function select: bits [17:15]
     * ALT5 = 0b010 = 2
     */
    unsigned int sel = mmio_read(GPFSEL1);
    sel &= ~(7 << 12);    /* Clear GPIO14 function bits */
    sel |= (2 << 12);     /* Set GPIO14 to ALT5 (TXD1) */
    sel &= ~(7 << 15);    /* Clear GPIO15 function bits */
    sel |= (2 << 15);     /* Set GPIO15 to ALT5 (RXD1) */
    mmio_write(GPFSEL1, sel);

    /*
     * Disable pull-up/down for pins 14 and 15.
     * BCM2711 uses GPIO_PUP_PDN_CNTRL_REGn (2 bits per pin).
     * Pin 14: bits [29:28], Pin 15: bits [31:30]
     * 0b00 = no resistor
     */
    unsigned int pup = mmio_read(GPIO_PUP_PDN_CNTRL_REG0);
    pup &= ~(3 << 28);    /* GPIO14: no pull */
    pup &= ~(3 << 30);    /* GPIO15: no pull */
    mmio_write(GPIO_PUP_PDN_CNTRL_REG0, pup);

    /* Enable transmitter and receiver */
    mmio_write(AUX_MU_CNTL, 3);
}

void uart_send(char c)
{
    /* Wait until transmitter is idle (bit 5 of LSR) */
    while (!(mmio_read(AUX_MU_LSR) & 0x20))
        ;
    mmio_write(AUX_MU_IO, (unsigned int)c);
}

void uart_puts(const char *s)
{
    while (*s) {
        if (*s == '\n')
            uart_send('\r');
        uart_send(*s++);
    }
}
