/*
 * Copyright (c) 2004, Swedish Institute of Computer Science.
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. Neither the name of the Institute nor the names of its contributors
 *    may be used to endorse or promote products derived from this software
 *    without specific prior written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE INSTITUTE AND CONTRIBUTORS ``AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE INSTITUTE OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
 * OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 *
 * Author: Adam Dunkels <adam@sics.se>
 *
 * Counting semaphores on top of protothreads.
 * "wait" blocks while count is zero; "signal" increments the count.
 */

#ifndef PT_SEM_H_
#define PT_SEM_H_

#include "pt.h"

struct pt_sem {
  unsigned int head, tail;
};

/**
 * Current semaphore count: head - tail.
 */
#define PT_SEM_COUNT(s) ((s)->head - (s)->tail)

/**
 * Initialize semaphore with count c.
 */
#define PT_SEM_INIT(s, c)        \
  do {                           \
    (s)->tail = 0;               \
    (s)->head = (c);             \
  } while(0)

/**
 * Wait (decrement). Blocks the protothread while count == 0.
 */
#define PT_SEM_WAIT(pt, s)                       \
  do {                                           \
    PT_WAIT_UNTIL(pt, PT_SEM_COUNT(s) > 0);      \
    ++(s)->tail;                                 \
  } while(0)

/**
 * Signal (increment). Never blocks.
 */
#define PT_SEM_SIGNAL(pt, s) (++(s)->head)

#endif /* PT_SEM_H_ */
