//! Telemetry serial output.

use crate::types::Message;

const TX_BUF_SIZE: usize = 512;
const FRAME_SENTINEL: u8 = 0x00;

pub struct TelemetryTx<W> {
    writer: W,
    cobs_buf: [u8; TX_BUF_SIZE],
}

impl<W: embedded_io::Write> TelemetryTx<W> {
    pub fn new(writer: W) -> Self {
        Self {
            writer,
            cobs_buf: [0u8; TX_BUF_SIZE],
        }
    }

    /// Encode and transmit a telemetry message over the serial link.
    pub fn send(&mut self, msg: &Message) -> Result<(), W::Error> {
        let serialized = postcard::to_allocvec(msg)
            .expect("serialization failed");

        let encoded_len = cobs::encode(&serialized, &mut self.cobs_buf);

        self.writer.write_all(&self.cobs_buf[..encoded_len])?;
        self.writer.write_all(&[FRAME_SENTINEL])?;
        Ok(())
    }
}
