
import { fromPromise } from 'xstate';
import type { StageConfig } from './types';

export const createCompensationActor = fromPromise(
  async ({ input }: { input: { config: StageConfig } }) => {
    await new Promise((resolve) => setTimeout(resolve, 5));
    return {
      name: input.config.name,
      success: true,
      message: `Compensated '${input.config.name}'`,
    };
  }
);
