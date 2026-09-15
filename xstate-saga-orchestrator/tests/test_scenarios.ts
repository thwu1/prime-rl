
import { sagaMachine } from './src/saga.js';
import { createActor, waitFor, fromPromise } from 'xstate';
import type {
  BookingConfirmation,
  BookingRequest,
  SagaOutput,
} from './src/saga.js';

const scenarioName = process.argv[2];

if (!scenarioName) {
  console.error('Usage: tsx test_scenarios.ts <scenario_name>');
  process.exit(2);
}

const defaultRequest: BookingRequest = {
  tripId: 'TRIP-001',
  flight: { flightId: 'AA100', price: 500 },
  hotel: { hotelId: 'HH200', price: 300 },
  carRental: { rentalId: 'CR300', price: 150 },
  requireAll: true,
  flightRetryPolicy: { maxAttempts: 0, baseDelayMs: 10 },
  hotelRetryPolicy: { maxAttempts: 0, baseDelayMs: 10 },
  carRentalRetryPolicy: { maxAttempts: 0, baseDelayMs: 10 },
};

function failingActor(errorMessage: string) {
  return fromPromise(async () => {
    throw new Error(errorMessage);
  });
}

function succeedingBookingActor(confirmationId: string, price: number) {
  return fromPromise(
    async (): Promise<BookingConfirmation> => ({
      confirmationId,
      status: 'confirmed',
      price,
    })
  );
}

function cancelActor(prefix: string) {
  return fromPromise(
    async ({
      input,
    }: {
      input: { confirmationId: string };
    }): Promise<string> => {
      return `Cancelled ${prefix} ${input.confirmationId}`;
    }
  );
}

function retryableBookingActor(
  failCount: number,
  confirmationId: string,
  price: number
) {
  let attempts = 0;
  return fromPromise(
    async (): Promise<BookingConfirmation> => {
      attempts++;
      if (attempts <= failCount) {
        throw new Error(`Attempt ${attempts} failed`);
      }
      return { confirmationId, status: 'confirmed', price };
    }
  );
}

/**
 * Build a SagaOutput from the actor snapshot's context and state value.
 */
function extractResult(snapshot: {
  value: unknown;
  context: {
    tripId: string;
    flightResult: BookingConfirmation | null;
    hotelResult: BookingConfirmation | null;
    carRentalResult: BookingConfirmation | null;
    compensationLog: string[];
  };
}): SagaOutput {
  const ctx = snapshot.context;
  const stateValue = snapshot.value as string;

  const statusMap: Record<string, SagaOutput['overallStatus']> = {
    completed: 'completed',
    partiallyCompleted: 'partially_completed',
    compensated: 'compensated',
    failed: 'failed',
  };

  const overallStatus: SagaOutput['overallStatus'] =
    statusMap[stateValue] ?? 'failed';

  let totalPrice = 0;
  if (overallStatus === 'completed') {
    totalPrice =
      (ctx.flightResult?.price ?? 0) +
      (ctx.hotelResult?.price ?? 0) +
      (ctx.carRentalResult?.price ?? 0);
  } else if (overallStatus === 'partially_completed') {
    if (ctx.flightResult?.status === 'confirmed')
      totalPrice += ctx.flightResult.price;
    if (ctx.hotelResult?.status === 'confirmed')
      totalPrice += ctx.hotelResult.price;
    if (ctx.carRentalResult?.status === 'confirmed')
      totalPrice += ctx.carRentalResult.price;
  }

  return {
    tripId: ctx.tripId,
    overallStatus,
    bookings: {
      flight: ctx.flightResult,
      hotel: ctx.hotelResult,
      carRental: ctx.carRentalResult,
    },
    totalPrice,
    compensationLog: ctx.compensationLog ?? [],
  };
}

// ===== Scenario Implementations =====

async function runAllSucceedRequireAll(): Promise<SagaOutput> {
  const testMachine = sagaMachine.provide({
    actors: {
      bookFlight: succeedingBookingActor('FL-CONF', 500),
      bookHotel: succeedingBookingActor('HT-CONF', 300),
      bookCarRental: succeedingBookingActor('CR-CONF', 150),
    },
  } as any);

  const actor = createActor(testMachine, {
    input: { request: { ...defaultRequest, requireAll: true } },
  });

  actor.start();
  actor.send({ type: 'START_BOOKING' });

  const snapshot = await waitFor(
    actor,
    (s) => s.status === 'done',
    { timeout: 10000 }
  );

  return extractResult(snapshot);
}

async function runFlightFailsRequireAll(): Promise<SagaOutput> {
  const testMachine = sagaMachine.provide({
    actors: {
      bookFlight: failingActor('No seats available'),
      bookHotel: succeedingBookingActor('HT-CONF', 300),
      bookCarRental: succeedingBookingActor('CR-CONF', 150),
      cancelFlight: cancelActor('flight'),
      cancelHotel: cancelActor('hotel'),
      cancelCarRental: cancelActor('car rental'),
    },
  } as any);

  const actor = createActor(testMachine, {
    input: { request: { ...defaultRequest, requireAll: true } },
  });

  actor.start();
  actor.send({ type: 'START_BOOKING' });

  const snapshot = await waitFor(
    actor,
    (s) => s.status === 'done',
    { timeout: 10000 }
  );

  return extractResult(snapshot);
}

async function runAllFail(): Promise<SagaOutput> {
  const testMachine = sagaMachine.provide({
    actors: {
      bookFlight: failingActor('No seats'),
      bookHotel: failingActor('No rooms'),
      bookCarRental: failingActor('No cars'),
    },
  } as any);

  const actor = createActor(testMachine, {
    input: { request: { ...defaultRequest, requireAll: true } },
  });

  actor.start();
  actor.send({ type: 'START_BOOKING' });

  const snapshot = await waitFor(
    actor,
    (s) => s.status === 'done',
    { timeout: 10000 }
  );

  return extractResult(snapshot);
}

async function runFlightFailsNotRequireAll(): Promise<SagaOutput> {
  const testMachine = sagaMachine.provide({
    actors: {
      bookFlight: failingActor('No seats'),
      bookHotel: succeedingBookingActor('HT-CONF', 300),
      bookCarRental: succeedingBookingActor('CR-CONF', 150),
    },
  } as any);

  const actor = createActor(testMachine, {
    input: { request: { ...defaultRequest, requireAll: false } },
  });

  actor.start();
  actor.send({ type: 'START_BOOKING' });

  const snapshot = await waitFor(
    actor,
    (s) => s.status === 'done',
    { timeout: 10000 }
  );

  return extractResult(snapshot);
}

async function runSnapshotPersistence(): Promise<SagaOutput> {
  const testMachine = sagaMachine.provide({
    actors: {
      bookFlight: succeedingBookingActor('FL-CONF', 500),
      bookHotel: succeedingBookingActor('HT-CONF', 300),
      bookCarRental: succeedingBookingActor('CR-CONF', 150),
    },
  } as any);

  const actor1 = createActor(testMachine, {
    input: { request: { ...defaultRequest, requireAll: true } },
  });
  actor1.start();

  const persisted = actor1.getPersistedSnapshot();
  actor1.stop();

  const actor2 = createActor(testMachine, {
    snapshot: persisted as any,
  });
  actor2.start();
  actor2.send({ type: 'START_BOOKING' });

  const snapshot = await waitFor(
    actor2,
    (s) => s.status === 'done',
    { timeout: 10000 }
  );

  return extractResult(snapshot);
}

async function runHotelFailsCarSucceedsRequireAll(): Promise<SagaOutput> {
  const testMachine = sagaMachine.provide({
    actors: {
      bookFlight: succeedingBookingActor('FL-CONF', 500),
      bookHotel: failingActor('No rooms'),
      bookCarRental: succeedingBookingActor('CR-CONF', 150),
      cancelFlight: cancelActor('flight'),
      cancelHotel: cancelActor('hotel'),
      cancelCarRental: cancelActor('car rental'),
    },
  } as any);

  const actor = createActor(testMachine, {
    input: { request: { ...defaultRequest, requireAll: true } },
  });

  actor.start();
  actor.send({ type: 'START_BOOKING' });

  const snapshot = await waitFor(
    actor,
    (s) => s.status === 'done',
    { timeout: 10000 }
  );

  return extractResult(snapshot);
}

async function runFlightRetrySucceeds(): Promise<SagaOutput> {
  const testMachine = sagaMachine.provide({
    actors: {
      bookFlight: retryableBookingActor(1, 'FL-CONF', 500),
      bookHotel: succeedingBookingActor('HT-CONF', 300),
      bookCarRental: succeedingBookingActor('CR-CONF', 150),
    },
    delays: {
      flightRetryDelay: 1,
      hotelRetryDelay: 1,
      carRentalRetryDelay: 1,
    },
  } as any);

  const actor = createActor(testMachine, {
    input: {
      request: {
        ...defaultRequest,
        requireAll: true,
        flightRetryPolicy: { maxAttempts: 2, baseDelayMs: 1 },
      },
    },
  });

  actor.start();
  actor.send({ type: 'START_BOOKING' });

  const snapshot = await waitFor(
    actor,
    (s) => s.status === 'done',
    { timeout: 10000 }
  );

  return extractResult(snapshot);
}

async function runFlightRetryExhausted(): Promise<SagaOutput> {
  const testMachine = sagaMachine.provide({
    actors: {
      bookFlight: failingActor('No seats ever'),
      bookHotel: succeedingBookingActor('HT-CONF', 300),
      bookCarRental: succeedingBookingActor('CR-CONF', 150),
      cancelFlight: cancelActor('flight'),
      cancelHotel: cancelActor('hotel'),
      cancelCarRental: cancelActor('car rental'),
    },
    delays: {
      flightRetryDelay: 1,
      hotelRetryDelay: 1,
      carRentalRetryDelay: 1,
    },
  } as any);

  const actor = createActor(testMachine, {
    input: {
      request: {
        ...defaultRequest,
        requireAll: true,
        flightRetryPolicy: { maxAttempts: 2, baseDelayMs: 1 },
      },
    },
  });

  actor.start();
  actor.send({ type: 'START_BOOKING' });

  const snapshot = await waitFor(
    actor,
    (s) => s.status === 'done',
    { timeout: 10000 }
  );

  return extractResult(snapshot);
}

async function runCarExpensiveCompensationOrder(): Promise<SagaOutput> {
  const testMachine = sagaMachine.provide({
    actors: {
      bookFlight: succeedingBookingActor('FL-CONF', 500),
      bookHotel: failingActor('No rooms'),
      bookCarRental: succeedingBookingActor('CR-CONF', 600),
      cancelFlight: cancelActor('flight'),
      cancelHotel: cancelActor('hotel'),
      cancelCarRental: cancelActor('car rental'),
    },
  } as any);

  const actor = createActor(testMachine, {
    input: {
      request: {
        ...defaultRequest,
        carRental: { rentalId: 'CR300', price: 600 },
        requireAll: true,
      },
    },
  });

  actor.start();
  actor.send({ type: 'START_BOOKING' });

  const snapshot = await waitFor(
    actor,
    (s) => s.status === 'done',
    { timeout: 10000 }
  );

  return extractResult(snapshot);
}

// ===== Main =====

try {
  let result: SagaOutput;

  switch (scenarioName) {
    case 'all_succeed_require_all':
      result = await runAllSucceedRequireAll();
      break;
    case 'flight_fails_require_all':
      result = await runFlightFailsRequireAll();
      break;
    case 'all_fail':
      result = await runAllFail();
      break;
    case 'flight_fails_not_require_all':
      result = await runFlightFailsNotRequireAll();
      break;
    case 'snapshot_persistence':
      result = await runSnapshotPersistence();
      break;
    case 'hotel_fails_car_succeeds_require_all':
      result = await runHotelFailsCarSucceedsRequireAll();
      break;
    case 'flight_retries_succeed':
      result = await runFlightRetrySucceeds();
      break;
    case 'flight_retries_exhausted':
      result = await runFlightRetryExhausted();
      break;
    case 'car_expensive_compensation_order':
      result = await runCarExpensiveCompensationOrder();
      break;
    default:
      console.error(`Unknown scenario: ${scenarioName}`);
      process.exit(2);
  }

  console.log(JSON.stringify(result));
  process.exit(0);
} catch (e: any) {
  console.error(`Scenario "${scenarioName}" failed: ${e.message}`);
  process.exit(1);
}
