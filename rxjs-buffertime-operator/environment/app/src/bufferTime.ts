import { Observable, OperatorFunction, SchedulerLike, Subscription, asyncScheduler } from 'rxjs';


export function bufferTime<T>(bufferTimeSpan: number, scheduler?: SchedulerLike): OperatorFunction<T, T[]>;
export function bufferTime<T>(
  bufferTimeSpan: number,
  bufferCreationInterval: number | null | undefined,
  scheduler?: SchedulerLike
): OperatorFunction<T, T[]>;
export function bufferTime<T>(
  bufferTimeSpan: number,
  bufferCreationInterval: number | null | undefined,
  maxBufferSize: number,
  scheduler?: SchedulerLike
): OperatorFunction<T, T[]>;

export function bufferTime<T>(bufferTimeSpan: number, ...otherArgs: any[]): OperatorFunction<T, T[]> {
  // Extract scheduler from args if last argument has a schedule method
  const scheduler: SchedulerLike =
    (otherArgs.length > 0 &&
      otherArgs[otherArgs.length - 1] != null &&
      typeof otherArgs[otherArgs.length - 1]?.schedule === 'function')
      ? otherArgs.pop()!
      : asyncScheduler;
  const bufferCreationInterval: number | null = (otherArgs[0] as number) ?? null;
  const maxBufferSize: number = (otherArgs[1] as number) || Infinity;

  return (source: Observable<T>): Observable<T[]> =>
    new Observable<T[]>((subscriber) => {
      let currentBuffer: T[] = [];
      const mainSub = new Subscription();

      // Schedule periodic buffer emission using a single repeating timer.
      // NOTE: This implementation has multiple issues that need to be fixed.
      mainSub.add(
        scheduler.schedule(function (this: any) {
          const buf = currentBuffer;
          currentBuffer = [];
          subscriber.next(buf);
          this.schedule(undefined, bufferTimeSpan);
        }, bufferTimeSpan)
      );

      mainSub.add(
        source.subscribe({
          next: (value: T) => {
            currentBuffer.push(value);
          },
          error: (err: any) => {
            subscriber.error(err);
          },
          complete: () => {
            subscriber.complete();
          },
        })
      );

      return mainSub;
    });
}
