export interface Column {
  name: string;
  path: string;
  type?: string;
  collection?: boolean;
}

export interface SelectExpression {
  column?: Column[];
  select?: SelectExpression[];
  forEach?: string;
  forEachOrNull?: string;
  repeat?: string[];
  unionAll?: SelectExpression[];
}

export interface WhereClause {
  path: string;
}

export interface ConstantDef {
  name: string;
  [key: string]: any;
}

export interface ViewDefinition {
  resource: string;
  status?: string;
  select: SelectExpression[];
  where?: WhereClause[];
  constant?: ConstantDef[];
}

export interface TestCase {
  title: string;
  tags?: string[];
  description?: string;
  view: ViewDefinition;
  expect?: Record<string, any>[];
  expectError?: boolean;
  expectCount?: number;
  expectColumns?: string[];
}

export interface TestFile {
  title: string;
  description?: string;
  fhirVersion?: string[];
  resources: Record<string, any>[];
  tests: TestCase[];
}

export type Row = Record<string, any>;
