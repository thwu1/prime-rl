//! Byte-stuffing framing layer
//!
//! Encodes messages so that a chosen sentinel byte (0x00) never appears
//! in the output. The sentinel can then serve as a frame delimiter on
//! the serial link. Messages on the wire look like:
//!
//!   <encoded_msg_1> 0x00 <encoded_msg_2> 0x00 ...
//!
//! The encoding works in blocks. Each block starts with a "code byte"
//! followed by data bytes:
//!
//!   code < 0xFF : (code - 1) non-zero data bytes follow, and an
//!                 implicit zero is inserted after them (unless this
//!                 is the last block in the frame).
//!
//!   code = 0xFF : exactly 254 non-zero data bytes follow, with NO
//!                 implicit zero appended. This is the maximum block
//!                 size and handles long runs of non-zero data by
//!                 splitting them into 254-byte chunks.

/// Encode a message. The output will contain no 0x00 bytes.
pub fn encode(data: &[u8]) -> Vec<u8> {
    let mut output = Vec::with_capacity(data.len() + data.len() / 254 + 1);
    let mut code_pos = 0;
    let mut block_count: u8 = 1;

    // Reserve space for the first code byte
    output.push(0);

    for &byte in data {
        if byte == 0x00 {
            // End current block: write the accumulated count
            output[code_pos] = block_count;
            block_count = 1;
            // Reserve space for next code byte
            code_pos = output.len();
            output.push(0);
        } else {
            output.push(byte);
            block_count += 1;
            if block_count == 0xFF {
                // Block full at 254 data bytes — flush with 0xFF code
                output[code_pos] = 0xFF;
                block_count = 1;
                code_pos = output.len();
                output.push(0);
            }
        }
    }

    // Finalize the last block
    output[code_pos] = block_count;

    output
}

/// Decode an encoded message back to the original data.
pub fn decode(encoded: &[u8]) -> core::result::Result<Vec<u8>, FrameError> {
    let mut output = Vec::with_capacity(encoded.len());
    let mut idx = 0;

    while idx < encoded.len() {
        let code = encoded[idx];
        idx += 1;

        if code == 0 {
            return Err(FrameError::UnexpectedZero);
        }

        let n_data = (code as usize) - 1;
        if idx + n_data > encoded.len() {
            return Err(FrameError::Truncated);
        }

        output.extend_from_slice(&encoded[idx..idx + n_data]);
        idx += n_data;

        // Append implicit zero unless:
        //  - this is a 0xFF block (254 data bytes, no implicit zero)
        //  - we've reached the end of the encoded data
        if code < 0xFF && idx < encoded.len() {
            output.push(0x00);
        }
    }

    Ok(output)
}

#[derive(Debug)]
pub enum FrameError {
    UnexpectedZero,
    Truncated,
}
