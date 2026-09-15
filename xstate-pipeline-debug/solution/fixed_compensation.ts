
import { fromPromise } from 'xstate';
import type { StageConfig } from './types';

export const createCompensationActor = fromPromise(
  async ({ input }: { input: { config: StageConfig } }) => {
    await new Promise((resolve) => setTimeout(resolve, 5));
    return {
      stageName: input.config.name,
      status: 'compensated' as const,
      output: `Compensated '${input.config.name}'`,
    };
  }
);
