A CI/CD pipeline orchestrator at `/app/` uses XState v5 state machines in TypeScript. The codebase fails TypeScript compilation and produces incorrect runtime behavior. Source files are in `/app/src/`: `types.ts`, `stages.ts`, `compensation.ts`, `pipeline.ts`.

**Required outcome:**

1. `npx tsc --noEmit` (run from `/app/` after `npm install`) must exit 0 with no errors.

2. The `pipelineMachine` exported from `/app/src/pipeline.ts` must satisfy these behavioral contracts when exercised via `pipelineMachine.provide()` with mock actors:

   **Successful pipeline:** When all stages pass, the machine reaches the `succeeded` final state with all 6 stage results recorded in `context.stageResults`, each with `status: 'passed'`, and `context.completedAt` set. No compensations run; `context.compensationResults` is empty.

   **Deploy failure:** When the deploy stage throws, the machine reaches the `failed` final state with `context.error` set. Before reaching `failed`, compensating transactions execute for every previously completed stage whose config has `compensatable: true`. Compensations run in reverse execution order. Each produces a `CompensationResult` entry collected in `context.compensationResults`.

   **Test failure:** When any test stage returns `status: 'failed'` (without throwing), the machine reaches `failed` without attempting deploy and without running compensations.

3. The parallel `testing` state's three regions (unit, integration, e2e) must all reach their final states before the machine evaluates test results.

**Constraints:**
- Preserve the existing module structure and exports
- Do not rename exported identifiers
- All actors and guards must be registered through `setup()` and referenced by string name
- Run `npm install` before type-checking

**Success criterion:** `npx tsc --noEmit` exits 0 AND all behavioral contracts above are satisfied.
