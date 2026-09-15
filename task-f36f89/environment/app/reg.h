#ifndef REG_H
#define REG_H

#include <stdint.h>

/* SysTick Timer (ARM Cortex-M3 System Timer) */
#define SYSTICK_CTRL    (*(volatile uint32_t *)0xE000E010)
#define SYSTICK_LOAD    (*(volatile uint32_t *)0xE000E014)
#define SYSTICK_VAL     (*(volatile uint32_t *)0xE000E018)

/* System Control Block */
#define SCB_ICSR        (*(volatile uint32_t *)0xE000ED04)
#define SCB_ICSR_PENDSVSET  (1u << 28)
#define SCB_SHPR3       (*(volatile uint32_t *)0xE000ED20)

/* MPS2-AN385 system clock (25 MHz in QEMU) */
#define CPU_CLOCK_HZ    25000000u
#define TICK_RATE_HZ    100u    /* 10 ms per tick */

#endif
