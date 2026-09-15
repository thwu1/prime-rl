#![no_std]
#![no_main]

extern crate alloc;

mod serial;
mod types;

use cortex_m_rt::entry;
use panic_halt as _;

use serial::TelemetryTx;
use types::Message;

// Hardware-specific initialization omitted (board support crate).
// The telemetry transmitter wraps the UART TX peripheral.
//
// Main loop: read sensors, build Message values, transmit via
// TelemetryTx::send(). The receiver must reverse the encoding
// pipeline to recover the original Message values.

#[entry]
fn main() -> ! {
    // let dp = pac::Peripherals::take().unwrap();
    // let uart_tx = hal::serial::Serial::new(dp.USART1, ...).split().1;
    // let mut telemetry = TelemetryTx::new(uart_tx);
    //
    // loop {
    //     let msg = read_sensors();
    //     telemetry.send(&msg).ok();
    //     cortex_m::asm::wfi();
    // }

    loop {
        cortex_m::asm::nop();
    }
}
