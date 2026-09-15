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
      let bufferRecords: { buffer: T[]; sub: Subscription }[] | null = [];
      let restartOnEmit = false;
      const mainSub = new Subscription();

      const emit = (record: { buffer: T[]; sub: Subscription }) => {
        const { buffer, sub } = record;
        sub.unsubscribe();
        if (bufferRecords) {
          const idx = bufferRecords.indexOf(record);
          if (idx >= 0) {
            bufferRecords.splice(idx, 1);
          }
        }
        subscriber.next(buffer);
        if (restartOnEmit) {
          startBuffer();
        }
      };

      const startBuffer = () => {
        if (bufferRecords) {
          const sub = new Subscription();
          mainSub.add(sub);
          const buffer: T[] = [];
          const record = { buffer, sub };
          bufferRecords.push(record);
          sub.add(
            scheduler.schedule(() => {
              emit(record);
            }, bufferTimeSpan)
          );
        }
      };

      if (bufferCreationInterval !== null && bufferCreationInterval >= 0) {
        // Schedule new buffer openings at the creation interval
        mainSub.add(
          scheduler.schedule(function (this: any) {
            startBuffer();
            this.schedule(undefined, bufferCreationInterval);
          }, bufferCreationInterval)
        );
      } else {
        restartOnEmit = true;
      }

      // Open the first buffer immediately
      startBuffer();

      mainSub.add(
        source.subscribe({
          next: (value: T) => {
            // Push value into ALL active buffers (enables overlapping windows)
            const recordsCopy = bufferRecords!.slice();
            for (const record of recordsCopy) {
              record.buffer.push(value);
              // Emit early if buffer reaches maxBufferSize
              if (record.buffer.length >= maxBufferSize) {
                emit(record);
              }
            }
          },
          error: (err: any) => {
            bufferRecords = null;
            subscriber.error(err);
          },
          complete: () => {
            // Flush all remaining active buffers in creation order
            while (bufferRecords && bufferRecords.length > 0) {
              subscriber.next(bufferRecords.shift()!.buffer);
            }
            subscriber.complete();
          },
        })
      );

      // Cleanup hook
      mainSub.add(() => {
        bufferRecords = null;
      });

      return mainSub;
    });
}
