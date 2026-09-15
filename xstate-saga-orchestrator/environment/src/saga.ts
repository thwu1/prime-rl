
import {
  assign,
  fromPromise,
  setup,
  createActor,
  waitFor,
} from 'xstate';

// ===== Types =====

export interface FlightBooking {
  flightId: string;
  price: number;
}

export interface HotelBooking {
  hotelId: string;
  price: number;
}

export interface CarRentalBooking {
  rentalId: string;
  price: number;
}

export interface RetryPolicy {
  maxAttempts: number;
  baseDelayMs: number;
}

export interface BookingRequest {
  tripId: string;
  flight: FlightBooking;
  hotel: HotelBooking;
  carRental: CarRentalBooking;
  requireAll: boolean;
  flightRetryPolicy: RetryPolicy;
  hotelRetryPolicy: RetryPolicy;
  carRentalRetryPolicy: RetryPolicy;
}

export interface BookingConfirmation {
  confirmationId: string;
  status: 'confirmed' | 'failed';
  price: number;
  error?: string;
}

export interface SagaOutput {
  tripId: string;
  overallStatus: 'completed' | 'partially_completed' | 'failed' | 'compensated';
  bookings: {
    flight: BookingConfirmation | null;
    hotel: BookingConfirmation | null;
    carRental: BookingConfirmation | null;
  };
  totalPrice: number;
  compensationLog: string[];
}

// ===== Default Service Actors =====

const defaultBookFlight = fromPromise(
  async ({
    input,
  }: {
    input: { flight: FlightBooking };
  }): Promise<BookingConfirmation> => {
    await new Promise((r) => setTimeout(r, 50));
    return {
      confirmationId: `FL-${input.flight.flightId}`,
      status: 'confirmed',
      price: input.flight.price,
    };
  }
);

const defaultBookHotel = fromPromise(
  async ({
    input,
  }: {
    input: { hotel: HotelBooking };
  }): Promise<BookingConfirmation> => {
    await new Promise((r) => setTimeout(r, 50));
    return {
      confirmationId: `HT-${input.hotel.hotelId}`,
      status: 'confirmed',
      price: input.hotel.price,
    };
  }
);

const defaultBookCarRental = fromPromise(
  async ({
    input,
  }: {
    input: { carRental: CarRentalBooking };
  }): Promise<BookingConfirmation> => {
    await new Promise((r) => setTimeout(r, 50));
    return {
      confirmationId: `CR-${input.carRental.rentalId}`,
      status: 'confirmed',
      price: input.carRental.price,
    };
  }
);

const defaultCancelFlight = fromPromise(
  async ({
    input,
  }: {
    input: { confirmationId: string };
  }): Promise<string> => {
    await new Promise((r) => setTimeout(r, 30));
    return `Cancelled flight ${input.confirmationId}`;
  }
);

const defaultCancelHotel = fromPromise(
  async ({
    input,
  }: {
    input: { confirmationId: string };
  }): Promise<string> => {
    await new Promise((r) => setTimeout(r, 30));
    return `Cancelled hotel ${input.confirmationId}`;
  }
);

const defaultCancelCarRental = fromPromise(
  async ({
    input,
  }: {
    input: { confirmationId: string };
  }): Promise<string> => {
    await new Promise((r) => setTimeout(r, 30));
    return `Cancelled car rental ${input.confirmationId}`;
  }
);

// ===== Machine Definition =====

export const sagaMachine = setup({
  types: {
    context: {} as {
      tripId: string;
      request: BookingRequest;
      flightResult: BookingConfirmation | null;
      hotelResult: BookingConfirmation | null;
      carRentalResult: BookingConfirmation | null;
      compensationLog: string[];
      requireAll: boolean;
      flightAttempts: number;
      hotelAttempts: number;
      carRentalAttempts: number;
      compensatedServices: string[];
    },
    input: {} as { request: BookingRequest },
  },
  delays: {
    flightRetryDelay: ({ context }) =>
      context.request.flightRetryPolicy.baseDelayMs + context.flightAttempts,
    hotelRetryDelay: ({ context }) =>
      context.request.hotelRetryPolicy.baseDelayMs + context.hotelAttempts,
    carRentalRetryDelay: ({ context }) =>
      context.request.carRentalRetryPolicy.baseDelayMs + context.carRentalAttempts,
  },
  actors: {
    bookFlight: defaultBookFlight,
    bookHotel: defaultBookHotel,
    bookCarRental: defaultBookCarRental,
    cancelFlight: defaultCancelFlight,
    cancelHotel: defaultCancelHotel,
    cancelCarRental: defaultCancelCarRental,
  },
  guards: {
    allSucceeded: ({ context }) => {
      return (
        context.flightResult?.status === 'confirmed' &&
        context.hotelResult?.status === 'confirmed' &&
        !(context.carRentalResult?.status === 'confirmed')
      );
    },
    needsCompensation: ({ context }) => {
      const anyFailed =
        context.flightResult?.status === 'failed' ||
        context.hotelResult?.status === 'failed' ||
        context.carRentalResult?.status === 'failed';
      const anySucceeded =
        context.flightResult?.status === 'confirmed' ||
        context.hotelResult?.status === 'confirmed' ||
        context.carRentalResult?.status === 'confirmed';
      return anyFailed && anySucceeded;
    },
    allFailed: ({ context }) => {
      return (
        context.flightResult?.status === 'failed' &&
        context.hotelResult?.status === 'failed' &&
        context.carRentalResult?.status === 'failed'
      );
    },
    flightCanRetry: ({ context }) =>
      context.flightAttempts < context.request.hotelRetryPolicy.maxAttempts,
    hotelCanRetry: ({ context }) =>
      context.hotelAttempts < context.request.hotelRetryPolicy.maxAttempts,
    carRentalCanRetry: ({ context }) =>
      context.carRentalAttempts < context.request.carRentalRetryPolicy.maxAttempts,
    flightWasConfirmed: ({ context }) => {
      return context.flightResult !== null;
    },
    hotelWasConfirmed: ({ context }) => {
      return context.hotelResult !== null;
    },
    carRentalWasConfirmed: ({ context }) => {
      return context.carRentalResult !== null;
    },
  },
}).createMachine({
  id: 'travelBookingSaga',
  initial: 'idle',
  context: ({ input }) => ({
    tripId: input.request.tripId,
    request: input.request,
    flightResult: null,
    hotelResult: null,
    carRentalResult: null,
    compensationLog: [],
    requireAll: true,
    flightAttempts: 0,
    hotelAttempts: 0,
    carRentalAttempts: 0,
    compensatedServices: [],
  }),
  states: {
    idle: {
      on: {
        START_BOOKING: { target: 'booking' },
      },
    },
    booking: {
      type: 'parallel',
      states: {
        flight: {
          initial: 'pending',
          states: {
            pending: {
              invoke: {
                src: 'bookFlight',
                input: ({ context }) => ({ flight: context.request.flight }),
                onDone: {
                  target: 'done',
                  actions: assign({
                    flightResult: ({ event }) => event.output,
                  }),
                },
                onError: [
                  {
                    guard: 'flightCanRetry',
                    target: 'retrying',
                    actions: assign({
                      flightAttempts: ({ context }) => context.flightAttempts + 1,
                    }),
                  },
                  {
                    target: 'done',
                    actions: assign({
                      flightAttempts: ({ context }) => context.flightAttempts + 1,
                      flightResult: ({ event }) => ({
                        confirmationId: '',
                        status: 'failed' as const,
                        price: 0,
                        error: String(
                          (event.error as Error)?.message ?? 'Flight booking failed'
                        ),
                      }),
                    }),
                  },
                ],
              },
            },
            retrying: {
              after: {
                flightRetryDelay: { target: 'pending' },
              },
            },
            done: { type: 'final' as const },
          },
        },
        hotel: {
          initial: 'pending',
          states: {
            pending: {
              invoke: {
                src: 'bookHotel',
                input: ({ context }) => ({ hotel: context.request.hotel }),
                onDone: {
                  target: 'done',
                  actions: assign({
                    hotelResult: ({ event }) => event.output,
                  }),
                },
                onError: [
                  {
                    guard: 'hotelCanRetry',
                    target: 'retrying',
                    actions: assign({
                      hotelAttempts: ({ context }) => context.hotelAttempts + 1,
                    }),
                  },
                  {
                    target: 'done',
                    actions: assign({
                      hotelAttempts: ({ context }) => context.hotelAttempts + 1,
                      hotelResult: ({ event }) => ({
                        confirmationId: '',
                        status: 'failed' as const,
                        price: 0,
                        error: String(
                          (event.error as Error)?.message ?? 'Hotel booking failed'
                        ),
                      }),
                    }),
                  },
                ],
              },
            },
            retrying: {
              after: {
                hotelRetryDelay: { target: 'pending' },
              },
            },
            done: { type: 'final' as const },
          },
        },
        carRental: {
          initial: 'pending',
          states: {
            pending: {
              invoke: {
                src: 'bookCarRental',
                input: ({ context }) => ({
                  carRental: context.request.carRental,
                }),
                onDone: {
                  target: 'completed',
                  actions: assign({
                    carRentalResult: ({ event }) => event.output,
                  }),
                },
                onError: [
                  {
                    guard: 'carRentalCanRetry',
                    target: 'retrying',
                    actions: assign({
                      carRentalAttempts: ({ context }) =>
                        context.carRentalAttempts + 1,
                    }),
                  },
                  {
                    target: 'completed',
                    actions: assign({
                      carRentalAttempts: ({ context }) =>
                        context.carRentalAttempts + 1,
                      carRentalResult: ({ event }) => ({
                        confirmationId: '',
                        status: 'failed' as const,
                        price: 0,
                        error: String(
                          (event.error as Error)?.message ??
                            'Car rental booking failed'
                        ),
                      }),
                    }),
                  },
                ],
              },
            },
            retrying: {
              after: {
                carRentalRetryDelay: { target: 'pending' },
              },
            },
            completed: {},
          },
        },
      },
      onDone: { target: 'evaluating' },
    },
    evaluating: {
      always: [
        { guard: 'allSucceeded', target: 'completed' },
        { guard: 'needsCompensation', target: 'compensating' },
        { guard: 'allFailed', target: 'failed' },
      ],
    },
    compensating: {
      type: 'parallel',
      states: {
        flight: {
          initial: 'checking',
          states: {
            checking: {
              always: [
                {
                  guard: 'flightWasConfirmed',
                  target: 'cancelling',
                },
                { target: 'skipped' },
              ],
            },
            cancelling: {
              invoke: {
                src: 'cancelFlight',
                input: ({ context }) => ({
                  confirmationId: context.flightResult!.confirmationId,
                }),
                onDone: {
                  target: 'cancelled',
                  actions: assign({
                    compensationLog: ({ context, event }) => [
                      ...context.compensationLog,
                      event.output,
                    ],
                  }),
                },
                onError: { target: 'cancelled' },
              },
            },
            cancelled: { type: 'final' as const },
            skipped: { type: 'final' as const },
          },
        },
        hotel: {
          initial: 'checking',
          states: {
            checking: {
              always: [
                {
                  guard: 'hotelWasConfirmed',
                  target: 'cancelling',
                },
                { target: 'skipped' },
              ],
            },
            cancelling: {
              invoke: {
                src: 'cancelHotel',
                input: ({ context }) => ({
                  confirmationId: context.hotelResult!.confirmationId,
                }),
                onDone: {
                  target: 'cancelled',
                  actions: assign({
                    compensationLog: ({ context, event }) => [
                      ...context.compensationLog,
                      event.output,
                    ],
                  }),
                },
                onError: { target: 'cancelled' },
              },
            },
            cancelled: { type: 'final' as const },
            skipped: { type: 'final' as const },
          },
        },
        carRental: {
          initial: 'checking',
          states: {
            checking: {
              always: [
                {
                  guard: 'carRentalWasConfirmed',
                  target: 'cancelling',
                },
                { target: 'skipped' },
              ],
            },
            cancelling: {
              invoke: {
                src: 'cancelCarRental',
                input: ({ context }) => ({
                  confirmationId: context.hotelResult!.confirmationId,
                }),
                onDone: {
                  target: 'cancelled',
                  actions: assign({
                    compensationLog: ({ context, event }) => [
                      ...context.compensationLog,
                      event.output,
                    ],
                  }),
                },
                onError: { target: 'cancelled' },
              },
            },
            cancelled: { type: 'final' as const },
            skipped: { type: 'final' as const },
          },
        },
      },
      onDone: { target: 'failed' },
    },
    completed: { type: 'final' as const },
    partiallyCompleted: { type: 'final' as const },
    compensated: { type: 'final' as const },
    failed: { type: 'final' as const },
  },
});

export { createActor, waitFor };
