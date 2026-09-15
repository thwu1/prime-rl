A travel booking saga orchestrator in `/app/src/saga.ts` uses XState v5 to coordinate parallel flight, hotel, and car rental bookings with compensation logic. The implementation has multiple interrelated bugs and is missing critical functionality. Fix all bugs and implement the required features.

**Workflow states:**

1. `idle` → on `START_BOOKING` → `booking`
2. `booking` (parallel): invokes `bookFlight`, `bookHotel`, `bookCarRental` actors. Each parallel branch must support configurable retry with exponential backoff. Each branch must reach a final state with its result stored in context. When all three branches complete → `evaluating`.
3. `evaluating` (eventless transitions with guards): all three confirmed → `completed`; `requireAll` is true and mixed results (some failed, some confirmed) → `compensating`; all three failed → `failed`; otherwise → `partiallyCompleted`.
4. `compensating` (**sequential**, not parallel): cancels only confirmed bookings, highest confirmed-booking price first. Each cancellation invokes the corresponding cancel actor with that booking's own confirmation ID and appends the result to `compensationLog`. When all confirmed bookings are compensated → `compensated`.
5. Terminal states: `completed`, `partiallyCompleted`, `compensated`, `failed`.

**Retry mechanism:**

`BookingRequest` includes per-service `RetryPolicy { maxAttempts, baseDelayMs }`. When a booking actor fails and retry attempts remain, the branch waits `baseDelayMs * 2^attemptNumber` milliseconds before re-invoking. Track per-service attempt counts in context (`flightAttempts`, `hotelAttempts`, `carRentalAttempts`, initialized to 0). After exhausting retries, record the booking as failed.

**Sequential compensation:**

The `compensating` state must execute cancellations one at a time, ordered by confirmed booking price descending. Track which services have been compensated via `compensatedServices: string[]` in context. The `compensationLog` must reflect execution order.

**Context:**
- `requireAll` from `input.request.requireAll`
- `compensationLog` accumulates cancellation result strings
- Compensation targets only `'confirmed'`-status bookings

**Success criteria:**
- `npx tsc --noEmit` passes in `/app`
- `pytest /tests/test_state.py` passes
- Snapshot persistence via `getPersistedSnapshot()` / `createActor({ snapshot })`
- Modify only `/app/src/saga.ts`
