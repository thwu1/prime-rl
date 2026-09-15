# Dual-Channel Timer with APB-Lite Interface — Specification

## Overview

A dual-channel programmable timer peripheral with an APB-Lite slave interface, interrupt support, and input-capture capability. Each channel has an independent 32-bit counter, compare register, and capture register. A shared prescaler divides the bus clock before feeding timer ticks to both channels.

## Register Map

| Address | Name        | Access | Description |
|---------|-------------|--------|-------------|
| 0x00    | GLOBAL_CTRL | R/W    | `[0]` global enable; `[15:8]` prescaler divisor |
| 0x04    | INT_EN      | R/W    | `[3:0]` interrupt enable mask |
| 0x08    | INT_FLAG    | R/W1C  | `[3:0]` interrupt flags (write-1-to-clear) |
| 0x10    | CH0_CTRL    | R/W    | `[0]` channel enable; `[1]` auto-reload; `[2]` capture enable; `[3]` capture edge select |
| 0x14    | CH0_CNT     | R/W    | Channel 0 counter value |
| 0x18    | CH0_CMP     | R/W    | Channel 0 compare value |
| 0x1C    | CH0_CAP     | R      | Channel 0 capture value |
| 0x20    | CH1_CTRL    | R/W    | Same layout as CH0_CTRL |
| 0x24    | CH1_CNT     | R/W    | Channel 1 counter value |
| 0x28    | CH1_CMP     | R/W    | Channel 1 compare value |
| 0x2C    | CH1_CAP     | R      | Channel 1 capture value |

## GLOBAL_CTRL (0x00)

- **Bit 0 — global_en**: When 1, the prescaler and all enabled channels run. When 0, the prescaler resets to 0 and no ticks are generated.
- **Bits 15:8 — prescaler_div**: The prescaler divides the bus clock by `(prescaler_div + 1)`. A value of 0 means every bus clock produces a tick (divide-by-1). A value of N means one tick every N+1 bus clocks.

## Prescaler Behavior

The prescaler maintains an 8-bit counter (`prescaler_cnt`). On each bus clock with `global_en=1`:

1. If `prescaler_cnt >= prescaler_div`: generate a tick, reset `prescaler_cnt` to 0.
2. Otherwise: increment `prescaler_cnt`, no tick.

When `global_en=0`: `prescaler_cnt` resets to 0 and tick is deasserted.

## Channel Counter

Each channel has a 32-bit counter that increments by 1 on each prescaler tick (when the channel is enabled via `CHn_CTRL[0]`).

- **Free-running mode** (`CHn_CMP = 0`): Counter increments until overflow at 0xFFFFFFFF, wraps to 0, and sets the overflow interrupt flag.
- **Compare-match mode** (`CHn_CMP != 0`): When `CHn_CNT == CHn_CMP`, a compare-match event fires. If auto-reload is enabled (`CHn_CTRL[1] = 1`), the counter resets to **0**. If auto-reload is disabled, the counter holds its value at the compare point (no further increment until software resets it).

An APB write to `CHn_CNT` loads the counter directly, taking priority over timer increments.

## Interrupt Flags (INT_FLAG, 0x08)

Bit layout: `[0]` CH0 compare match, `[1]` CH0 overflow, `[2]` CH1 compare match, `[3]` CH1 overflow.

Flags are **set** by hardware events (OR'd in). Flags are **cleared** by software using **write-1-to-clear** (W1C): writing a 1 to a flag bit clears that bit; writing a 0 to a bit leaves it unchanged.

The `irq` output is asserted when any enabled interrupt flag is set: `irq = |(INT_FLAG & INT_EN)`.

## Capture

Each channel has a capture register (`CHn_CAP`) and an external capture input. Capture is enabled by `CHn_CTRL[2]`.

- **Edge select** (`CHn_CTRL[3]`): 0 = capture on **rising edge**, 1 = capture on **falling edge**.

When a selected edge is detected (through a 2-stage synchronizer), the current counter value is latched into `CHn_CAP`.

## APB-Lite Interface

- Single-cycle access: `pready` is always asserted.
- Write: data is captured when `psel & penable & pwrite`.
- Read: `prdata` is driven combinationally based on `paddr` when `psel & ~pwrite`.
- The read data mux returns the register value corresponding to the addressed offset. Each channel's registers are at their own distinct addresses as listed in the register map.
