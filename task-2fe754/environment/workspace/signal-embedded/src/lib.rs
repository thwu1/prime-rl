#![no_std]

extern crate alloc;

use alloc::vec::Vec;
use signal_core::types::SignalMessage;

/// Build-time generated format string for the default message.
pub const DEFAULT_MSG_FMT: &str = env!("DEFAULT_MSG_FMT");

pub struct EmbeddedProcessor {
    queue: Vec<SignalMessage>,
    max_queue: usize,
}

impl EmbeddedProcessor {
    pub fn new(max_queue: usize) -> Self {
        Self {
            queue: Vec::new(),
            max_queue,
        }
    }

    pub fn enqueue(&mut self, msg: SignalMessage) -> bool {
        if self.queue.len() < self.max_queue {
            self.queue.push(msg);
            true
        } else {
            false
        }
    }

    pub fn drain(&mut self) -> Vec<SignalMessage> {
        core::mem::take(&mut self.queue)
    }

    pub fn pending_count(&self) -> usize {
        self.queue.len()
    }
}
