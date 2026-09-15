
export interface StageConfig {
  name: string;
  command: string;
  retries: number;
  timeoutMs: number;
  compensatable: boolean;
  compensationCommand?: string;
}

export interface StageResult {
  stageName: string;
  status: 'passed' | 'failed';
  output: string;
  durationMs: number;
}

export interface CompensationResult {
  stageName: string;
  status: 'compensated' | 'compensation_failed';
  output: string;
}

export interface PipelineContext {
  pipelineName: string;
  stageResults: Record<string, StageResult>;
  currentStageIndex: number;
  error: string | null;
  startedAt: number;
  completedAt: number | null;
  compensationResults: CompensationResult[];
  pendingCompensations: string[];
}

export type PipelineEvent =
  | { type: 'pipeline.start' }
  | { type: 'pipeline.cancel' };
