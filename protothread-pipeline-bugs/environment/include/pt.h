/*
 * Copyright (c) 2004-2005, Swedish Institute of Computer Science.
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
 * Protothreads: lightweight stackless threads for C.
 * Each protothread requires only 2 bytes of state (an unsigned short).
 *
 * IMPORTANT: Because protothreads do not save the stack context across
 * a blocking call, LOCAL VARIABLES ARE NOT PRESERVED when the protothread
 * blocks. Local variables that must survive across a blocking point
 * should be declared 'static' or stored in a context structure.
 *
 * IMPORTANT: The default LC implementation uses switch/case internally.
 * Do NOT use switch() statements inside a protothread body, as the
 * case labels will conflict with the LC mechanism.
 */

#ifndef PT_H_
#define PT_H_

#include "lc.h"

struct pt {
  lc_t lc;
};

#define PT_WAITING 0
#define PT_YIELDED 1
#define PT_EXITED  2
#define PT_ENDED   3

/**
 * Initialize a protothread. Must be called before first use.
 */
#define PT_INIT(pt)   LC_INIT((pt)->lc)

/**
 * Declare a protothread function. Usage:
 *   static PT_THREAD(my_thread(struct pt *pt)) { ... }
 */
#define PT_THREAD(name_args) char name_args

/**
 * Declare the start of a protothread body.
 * Must be paired with PT_END().
 */
#define PT_BEGIN(pt) { char PT_YIELD_FLAG = 1; if (PT_YIELD_FLAG) {;} LC_RESUME((pt)->lc)

/**
 * Declare the end of a protothread body.
 */
#define PT_END(pt) LC_END((pt)->lc); PT_YIELD_FLAG = 0; \
                   PT_INIT(pt); return PT_ENDED; }

/**
 * Block and wait until condition is true.
 */
#define PT_WAIT_UNTIL(pt, condition)        \
  do {                                      \
    LC_SET((pt)->lc);                       \
    if(!(condition)) {                      \
      return PT_WAITING;                    \
    }                                       \
  } while(0)

/**
 * Block and wait while condition is true.
 */
#define PT_WAIT_WHILE(pt, cond)  PT_WAIT_UNTIL((pt), !(cond))

/**
 * Block until a child protothread completes.
 */
#define PT_WAIT_THREAD(pt, thread) PT_WAIT_WHILE((pt), PT_SCHEDULE(thread))

/**
 * Spawn a child protothread and wait until it exits.
 */
#define PT_SPAWN(pt, child, thread)         \
  do {                                      \
    PT_INIT((child));                       \
    PT_WAIT_THREAD((pt), (thread));         \
  } while(0)

/**
 * Restart the protothread from PT_BEGIN.
 */
#define PT_RESTART(pt)                      \
  do {                                      \
    PT_INIT(pt);                            \
    return PT_WAITING;                      \
  } while(0)

/**
 * Exit the protothread immediately.
 */
#define PT_EXIT(pt)                         \
  do {                                      \
    PT_INIT(pt);                            \
    return PT_EXITED;                       \
  } while(0)

/**
 * Schedule a protothread. Returns non-zero if still running.
 */
#define PT_SCHEDULE(f) ((f) < PT_EXITED)

/**
 * Yield from the protothread (return, resume here next call).
 */
#define PT_YIELD(pt)                        \
  do {                                      \
    PT_YIELD_FLAG = 0;                      \
    LC_SET((pt)->lc);                       \
    if(PT_YIELD_FLAG == 0) {                \
      return PT_YIELDED;                    \
    }                                       \
  } while(0)

/**
 * Yield until a condition becomes true.
 */
#define PT_YIELD_UNTIL(pt, cond)            \
  do {                                      \
    PT_YIELD_FLAG = 0;                      \
    LC_SET((pt)->lc);                       \
    if((PT_YIELD_FLAG == 0) || !(cond)) {   \
      return PT_YIELDED;                    \
    }                                       \
  } while(0)

#endif /* PT_H_ */
