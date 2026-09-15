#!/usr/bin/env python3
"""
Fix bugs and implement the compensation system in the pipeline orchestrator.

Bug inventory:
  types.ts:
    - PipelineContext missing compensationResults and pendingCompensations fields
  stages.ts:
    1. Missing `fromPromise` import from 'xstate'
    2. Actor input key is 'stageConfig' but pipeline passes 'config'
  compensation.ts:
    3. Return shape doesn't match CompensationResult interface
  pipeline.ts:
    4. Guard uses `context.results` instead of `context.stageResults`
    5. Assign actions access `event.output.data` instead of `event.output`
    6. Parallel test regions' invoke onDone missing `target: 'done'`
    7. Delayed transition key 'stageTimeout' doesn't match registered 'STAGE_TIMEOUT'
    8. Evaluating state's always transitions missing default fallback to 'failed'
    9. createCompensationActor imported but not registered in setup().actors
    10. Missing hasMoreCompensations guard
    11. Context initial values missing compensation tracking fields
    12. Compensating state is a non-functional stub — must be fully implemented
"""

# ── Fix types.ts ─────────────────────────────────────────────────────────────

with open('/app/src/types.ts', 'r') as f:
    types_content = f.read()

# Add compensation tracking fields to PipelineContext
types_content = types_content.replace(
    '  completedAt: number | null;\n}',
    '  completedAt: number | null;\n  compensationResults: CompensationResult[];\n  pendingCompensations: string[];\n}'
)

with open('/app/src/types.ts', 'w') as f:
    f.write(types_content)

print('Fixed types.ts: added compensationResults and pendingCompensations to PipelineContext')

# ── Fix stages.ts ────────────────────────────────────────────────────────────

with open('/app/src/stages.ts', 'r') as f:
    stages = f.read()

# Fix 1: Add fromPromise import
stages = "import { fromPromise } from 'xstate';\n" + stages

# Fix 2: Actor expects { stageConfig } but callers pass { config }
stages = stages.replace(
    '{ input: { stageConfig: StageConfig } }',
    '{ input: { config: StageConfig } }'
)
stages = stages.replace('input.stageConfig', 'input.config')

with open('/app/src/stages.ts', 'w') as f:
    f.write(stages)

print('Fixed stages.ts: added fromPromise import, aligned input key')

# ── Fix compensation.ts ─────────────────────────────────────────────────────

with open('/app/src/compensation.ts', 'r') as f:
    comp = f.read()

# Fix 3: Return shape must match CompensationResult interface
comp = comp.replace(
    "      name: input.config.name,\n"
    "      success: true,\n"
    "      message: `Compensated '${input.config.name}'`,",
    "      stageName: input.config.name,\n"
    "      status: 'compensated' as const,\n"
    "      output: `Compensated '${input.config.name}'`,"
)

with open('/app/src/compensation.ts', 'w') as f:
    f.write(comp)

print('Fixed compensation.ts: aligned return shape with CompensationResult')

# ── Fix pipeline.ts ──────────────────────────────────────────────────────────

with open('/app/src/pipeline.ts', 'r') as f:
    pipeline = f.read()

# Fix 4: Guard references context.results but the context type has stageResults
pipeline = pipeline.replace('context.results[', 'context.stageResults[')

# Fix 5: onDone assign actions access event.output.data but fromPromise output
# is event.output directly (no .data wrapper in XState v5)
pipeline = pipeline.replace('event.output.data', 'event.output')

# Fix 6: Parallel test regions' onDone missing target: 'done'
buggy_ondone = "                onDone: {\n                  actions: assign({"
fixed_ondone = "                onDone: {\n                  target: 'done',\n                  actions: assign({"
pipeline = pipeline.replace(buggy_ondone, fixed_ondone)

# Fix 7: The after block uses 'stageTimeout' but delays registers 'STAGE_TIMEOUT'
pipeline = pipeline.replace('stageTimeout:', 'STAGE_TIMEOUT:')

# Fix 8: Evaluating state missing default fallback transition
pipeline = pipeline.replace(
    "          target: 'deploying',\n        },\n      ],",
    "          target: 'deploying',\n        },\n        {\n          target: 'failed',\n        },\n      ],"
)

# Fix 9: Register createCompensationActor in setup().actors
pipeline = pipeline.replace(
    "    // Note: createCompensationActor imported but not registered here",
    "    runCompensation: createCompensationActor,"
)

# Fix 10: Add hasMoreCompensations guard
pipeline = pipeline.replace(
    "      );\n    },\n  },\n  delays:",
    "      );\n    },\n    hasMoreCompensations: ({ context }) =>\n      context.pendingCompensations.length > 0,\n  },\n  delays:"
)

# Fix 11: Add initial context values for compensation tracking
pipeline = pipeline.replace(
    "    completedAt: null,\n  },\n  states:",
    "    completedAt: null,\n    compensationResults: [],\n    pendingCompensations: [],\n  },\n  states:"
)

# Fix 12: Replace compensating stub with full compound-state implementation
old_compensating = """\
    compensating: {
      entry: assign({
        error: ({ context }) =>
          context.error ?? 'Pipeline failed, initiating compensation',
      }),
      after: {
        500: 'failed',
      },
    },"""

new_compensating = """\
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
    },"""

pipeline = pipeline.replace(old_compensating, new_compensating)

with open('/app/src/pipeline.ts', 'w') as f:
    f.write(pipeline)

print('Fixed pipeline.ts: all bugs fixed, compensation system implemented')
print('All fixes applied successfully')
