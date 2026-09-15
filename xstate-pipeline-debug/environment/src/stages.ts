
import type { StageConfig, StageResult } from './types';

export const createStageActor = fromPromise(
  async ({ input }: { input: { stageConfig: StageConfig } }) => {
    const start = Date.now();
    const config = input.stageConfig;

    const result = await executeStage(config);

    return {
      stageName: config.name,
      status: result.success ? ('passed' as const) : ('failed' as const),
      output: result.output,
      durationMs: Date.now() - start,
    } satisfies StageResult;
  }
);

async function executeStage(
  config: StageConfig
): Promise<{ success: boolean; output: string }> {
  await new Promise((resolve) => setTimeout(resolve, 10));
  return {
    success: true,
    output: `Stage '${config.name}' completed successfully`,
  };
}
