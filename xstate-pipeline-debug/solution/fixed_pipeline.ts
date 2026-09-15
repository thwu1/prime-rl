
import { setup, assign, createActor } from 'xstate';
import type {
  PipelineContext,
  PipelineEvent,
  StageConfig,
  StageResult,
} from './types';
import { createStageActor } from './stages';
import { createCompensationActor } from './compensation';

const STAGE_CONFIGS: Record<string, StageConfig> = {
  lint: {
    name: 'lint',
    command: 'npm run lint',
    retries: 0,
    timeoutMs: 30_000,
    compensatable: true,
    compensationCommand: 'clean-lint-cache',
  },
  build: {
    name: 'build',
    command: 'npm run build',
    retries: 1,
    timeoutMs: 60_000,
    compensatable: true,
    compensationCommand: 'rm -rf dist',
  },
  'unit-test': {
    name: 'unit-test',
    command: 'npm test -- --unit',
    retries: 2,
    timeoutMs: 60_000,
    compensatable: false,
  },
  'integration-test': {
    name: 'integration-test',
    command: 'npm test -- --integration',
    retries: 1,
    timeoutMs: 120_000,
    compensatable: false,
  },
  'e2e-test': {
    name: 'e2e-test',
    command: 'npm test -- --e2e',
    retries: 1,
    timeoutMs: 180_000,
    compensatable: false,
  },
  deploy: {
    name: 'deploy',
    command: 'deploy.sh',
    retries: 0,
    timeoutMs: 300_000,
    compensatable: true,
    compensationCommand: 'rollback.sh',
  },
};

export const pipelineMachine = setup({
  types: {
    context: {} as PipelineContext,
    events: {} as PipelineEvent,
  },
  actors: {
    runStage: createStageActor,
    runCompensation: createCompensationActor,
  },
  guards: {
    allTestsPassed: ({ context }) => {
      const testStages = ['unit-test', 'integration-test', 'e2e-test'];
      return testStages.every(
        (name) => context.stageResults[name]?.status === 'passed'
      );
    },
    hasMoreCompensations: ({ context }) =>
      context.pendingCompensations.length > 0,
  },
  delays: {
    STAGE_TIMEOUT: 30_000,
  },
}).createMachine({
  id: 'pipeline',
  initial: 'idle',
  context: {
    pipelineName: 'default-pipeline',
    stageResults: {},
    currentStageIndex: 0,
    error: null,
    startedAt: 0,
    completedAt: null,
    compensationResults: [],
    pendingCompensations: [],
  },
  states: {
    idle: {
      on: {
        'pipeline.start': {
          target: 'linting',
          actions: assign({
            startedAt: () => Date.now(),
            stageResults: () => ({}),
            error: () => null,
            completedAt: () => null,
          }),
        },
      },
    },
    linting: {
      invoke: {
        src: 'runStage',
        input: () => ({ config: STAGE_CONFIGS['lint'] }),
        onDone: {
          target: 'building',
          actions: assign({
            stageResults: ({ context, event }) => ({
              ...context.stageResults,
              [event.output.stageName]: event.output,
            }),
          }),
        },
        onError: {
          target: 'failed',
          actions: assign({
            error: ({ event }) => String(event.error),
          }),
        },
      },
      after: {
        STAGE_TIMEOUT: {
          target: 'failed',
          actions: assign({ error: () => 'Lint stage timed out' }),
        },
      },
    },
    building: {
      invoke: {
        src: 'runStage',
        input: () => ({ config: STAGE_CONFIGS['build'] }),
        onDone: {
          target: 'testing',
          actions: assign({
            stageResults: ({ context, event }) => ({
              ...context.stageResults,
              [event.output.stageName]: event.output,
            }),
          }),
        },
        onError: {
          target: 'compensating',
          actions: assign({
            error: ({ event }) => String(event.error),
          }),
        },
      },
    },
    testing: {
      type: 'parallel',
      states: {
        unit: {
          initial: 'running',
          states: {
            running: {
              invoke: {
                src: 'runStage',
                input: () => ({ config: STAGE_CONFIGS['unit-test'] }),
                onDone: {
                  target: 'done',
                  actions: assign({
                    stageResults: ({ context, event }) => ({
                      ...context.stageResults,
                      [event.output.stageName]: event.output,
                    }),
                  }),
                },
                onError: {
                  target: 'done',
                  actions: assign({
                    error: ({ event }) => String(event.error),
                  }),
                },
              },
            },
            done: { type: 'final' },
          },
        },
        integration: {
          initial: 'running',
          states: {
            running: {
              invoke: {
                src: 'runStage',
                input: () => ({ config: STAGE_CONFIGS['integration-test'] }),
                onDone: {
                  target: 'done',
                  actions: assign({
                    stageResults: ({ context, event }) => ({
                      ...context.stageResults,
                      [event.output.stageName]: event.output,
                    }),
                  }),
                },
                onError: {
                  target: 'done',
                  actions: assign({
                    error: ({ event }) => String(event.error),
                  }),
                },
              },
            },
            done: { type: 'final' },
          },
        },
        e2e: {
          initial: 'running',
          states: {
            running: {
              invoke: {
                src: 'runStage',
                input: () => ({ config: STAGE_CONFIGS['e2e-test'] }),
                onDone: {
                  target: 'done',
                  actions: assign({
                    stageResults: ({ context, event }) => ({
                      ...context.stageResults,
                      [event.output.stageName]: event.output,
                    }),
                  }),
                },
                onError: {
                  target: 'done',
                  actions: assign({
                    error: ({ event }) => String(event.error),
                  }),
                },
              },
            },
            done: { type: 'final' },
          },
        },
      },
      onDone: 'evaluating',
    },
    evaluating: {
      always: [
        {
          guard: 'allTestsPassed',
          target: 'deploying',
        },
        {
          target: 'failed',
        },
      ],
    },
    deploying: {
      invoke: {
        src: 'runStage',
        input: () => ({ config: STAGE_CONFIGS['deploy'] }),
        onDone: {
          target: 'succeeded',
          actions: assign({
            stageResults: ({ context, event }) => ({
              ...context.stageResults,
              [event.output.stageName]: event.output,
            }),
          }),
        },
        onError: {
          target: 'compensating',
          actions: assign({
            error: ({ event }) => String(event.error),
          }),
        },
      },
    },
    compensating: {
      entry: assign({
        pendingCompensations: ({ context }) => {
          const stageOrder = ['lint', 'build', 'unit-test', 'integration-test', 'e2e-test', 'deploy'];
          return stageOrder
            .filter(
              (name) =>
                context.stageResults[name]?.status === 'passed' &&
                STAGE_CONFIGS[name]?.compensatable
            )
            .reverse();
        },
      }),
      initial: 'checking',
      states: {
        checking: {
          always: [
            { guard: 'hasMoreCompensations', target: 'executing' },
            { target: 'done' },
          ],
        },
        executing: {
          invoke: {
            src: 'runCompensation',
            input: ({ context }) => ({
              config: STAGE_CONFIGS[context.pendingCompensations[0]],
            }),
            onDone: {
              target: 'checking',
              actions: assign({
                compensationResults: ({ context, event }) => [
                  ...context.compensationResults,
                  event.output,
                ],
                pendingCompensations: ({ context }) =>
                  context.pendingCompensations.slice(1),
              }),
            },
            onError: {
              target: 'checking',
              actions: assign({
                compensationResults: ({ context }) => [
                  ...context.compensationResults,
                  {
                    stageName: context.pendingCompensations[0],
                    status: 'compensation_failed' as const,
                    output: 'Compensation failed',
                  },
                ],
                pendingCompensations: ({ context }) =>
                  context.pendingCompensations.slice(1),
              }),
            },
          },
        },
        done: {
          type: 'final',
        },
      },
      onDone: {
        target: 'failed',
      },
    },
    succeeded: {
      type: 'final',
      entry: assign({
        completedAt: () => Date.now(),
      }),
    },
    failed: {
      type: 'final',
    },
  },
});

export function runPipeline() {
  const actor = createActor(pipelineMachine);
  actor.start();
  actor.send({ type: 'pipeline.start' });
  return actor;
}
