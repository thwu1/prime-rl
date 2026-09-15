#ifndef MMIO_H
#define MMIO_H

/*
 * mmio.h - BCM2711 (Raspberry Pi 4) Memory-Mapped I/O definitions
 *
 * Defines peripheral base addresses and register offsets for
 * bare-metal Mini UART and GPIO configuration.
 *
 * Reference: BCM2711 ARM Peripherals datasheet
 */

/* BCM2711 peripheral base address (active ARM-side mapping) */
#define MMIO_BASE       0x3F000000

/* GPIO register base */
#define GPIO_BASE       (MMIO_BASE + 0x200000)

/* GPIO Function Select registers (3 bits per pin, 10 pins per register) */
#define GPFSEL0         (GPIO_BASE + 0x00)
#define GPFSEL1         (GPIO_BASE + 0x08)

/* GPIO Pin Output Set / Clear registers */
#define GPSET0          (GPIO_BASE + 0x1C)
#define GPCLR0          (GPIO_BASE + 0x28)

/* GPIO Pull-up / Pull-down control (BCM2711 style) */
#define GPIO_PUP_PDN_CNTRL_REG0  (GPIO_BASE + 0xE4)

/* Auxiliary peripherals base (Mini UART, SPI1, SPI2) */
#define AUX_BASE        (MMIO_BASE + 0x215000)
#define AUX_ENABLES     (AUX_BASE + 0x04)
#define AUX_MU_IO       (AUX_BASE + 0x40)
#define AUX_MU_IER      (AUX_BASE + 0x44)
#define AUX_MU_IIR      (AUX_BASE + 0x48)
#define AUX_MU_LCR      (AUX_BASE + 0x4C)
#define AUX_MU_MCR      (AUX_BASE + 0x50)
#define AUX_MU_LSR      (AUX_BASE + 0x54)
#define AUX_MU_CNTL     (AUX_BASE + 0x60)
#define AUX_MU_BAUD     (AUX_BASE + 0x68)

/* RPi4 system clock frequency */
#define SYS_CLOCK_FREQ  500000000
#define UART_BAUD_RATE  115200

/*
 * Mini UART baud rate register value.
 * Formula: sys_clk / (8 * baud_rate) - 1
 */
#define AUX_MU_BAUD_VAL 270

/* Low-level MMIO access primitives */
static inline void mmio_write(unsigned long reg, unsigned int val)
{
    *(volatile unsigned int *)reg = val;
}

static inline unsigned int mmio_read(unsigned long reg)
{
    return *(volatile unsigned int *)reg;
}

#endif /* MMIO_H */
