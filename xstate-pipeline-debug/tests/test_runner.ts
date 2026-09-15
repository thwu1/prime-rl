
import { createActor, waitFor, fromPromise } from 'xstate';
import { pipelineMachine } from './src/pipeline';
import type { StageConfig, StageResult } from './src/types';

const scenario = process.argv[2];

function makeStageActor(failStage?: string, throwStage?: string) {
  return fromPromise(
    async ({ input }: { input: { config: StageConfig } }) => {
      await new Promise((r) => setTimeout(r, 5));

      if (input.config.name === throwStage) {
        throw new Error(`Stage '${input.config.name}' failed`);
      }

      const status =
        input.config.name === failStage ? 'failed' : 'passed';

      return {
        stageName: input.config.name,
        status: status as 'passed' | 'failed',
        output: `${input.config.name}: ${status}`,
        durationMs: 5,
      } satisfies StageResult;
    }
  );
}

async function runScenario(name: string) {
  let machine = pipelineMachine;

  if (name === 'deploy_fail') {
    machine = pipelineMachine.provide({
      actors: { runStage: makeStageActor(undefined, 'deploy') },
    });
  } else if (name === 'test_fail') {
    machine = pipelineMachine.provide({
      actors: { runStage: makeStageActor('unit-test') },
    });
  }

  const actor = createActor(machine);
  let deployAttempted = false;

  actor.subscribe((snapshot) => {
    if (typeof snapshot.value === 'string' && snapshot.value === 'deploying') {
      deployAttempted = true;
    }
  });

  actor.start();
  actor.send({ type: 'pipeline.start' });

  try {
    const snapshot = await waitFor(
      actor,
      (s) => s.status === 'done',
      { timeout: 15_000 }
    );

    const ctx = snapshot.context as Record<string, unknown>;
    const stageResults = (ctx.stageResults || {}) as Record<string, StageResult>;
    const compensationResults = (ctx.compensationResults || []) as Array<Record<string, unknown>>;

    const result = {
      final_state: snapshot.value,
      stage_count: Object.keys(stageResults).length,
      all_passed: Object.values(stageResults).every(
        (r: StageResult) => r.status === 'passed'
      ),
      has_error: ctx.error !== null && ctx.error !== undefined,
      completed_at: ctx.completedAt,
      deploy_attempted: deployAttempted,
      stage_names: Object.keys(stageResults).sort(),
      compensation_count: compensationResults.length,
      compensation_stages: compensationResults.map(
        (r: Record<string, unknown>) => r.stageName
      ),
      compensation_all_succeeded: compensationResults.every(
        (r: Record<string, unknown>) => r.status === 'compensated'
      ),
    };

    console.log(JSON.stringify(result));
  } catch (e) {
    console.log(JSON.stringify({ error: String(e) }));
    process.exit(1);
  }
}

runScenario(scenario!);
