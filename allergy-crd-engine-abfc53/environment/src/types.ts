
export enum AllergenCategory {
  TREE_POLLENS = 'TREE_POLLENS',
  GRASS_POLLENS = 'GRASS_POLLENS',
  WEED_POLLENS = 'WEED_POLLENS',
  ANIMALS = 'ANIMALS',
  MITES = 'MITES',
  MOLDS = 'MOLDS',
  VENOMS = 'VENOMS',
  LATEX = 'LATEX',
  FOOD_PEANUT = 'FOOD_PEANUT',
  FOOD_TREE_NUTS = 'FOOD_TREE_NUTS',
  FOOD_EGG = 'FOOD_EGG',
  FOOD_MILK = 'FOOD_MILK',
  FOOD_FISH = 'FOOD_FISH',
  FOOD_SHELLFISH = 'FOOD_SHELLFISH',
  FOOD_SOY = 'FOOD_SOY',
  FOOD_WHEAT = 'FOOD_WHEAT',
  FOOD_PEACH = 'FOOD_PEACH',
  FOOD_SESAME = 'FOOD_SESAME',
  FOOD_FRUITS_VEGETABLES = 'FOOD_FRUITS_VEGETABLES',
  FOOD_MEAT = 'FOOD_MEAT',
  INSECTS = 'INSECTS',
  PARASITES = 'PARASITES',
  CCD = 'CCD'
}

export enum AllergenType {
  MAJOR = 'MAJOR',
  MINOR = 'MINOR'
}

export enum MolecularFamily {
  PR10 = 'PR10',
  LTP = 'LTP',
  PROFILINS = 'PROFILINS',
  POLCALCINS = 'POLCALCINS',
  TROPOMYOSINS = 'TROPOMYOSINS',
  STORAGE_PROTEINS = 'STORAGE_PROTEINS',
  SERUM_ALBUMINS = 'SERUM_ALBUMINS',
  LIPOCALINS = 'LIPOCALINS',
  PARVALBUMINS = 'PARVALBUMINS'
}

export enum SymptomSeverity {
  ASYMPTOMATIC = 'ASYMPTOMATIC',
  LOCAL = 'LOCAL',
  SYSTEMIC = 'SYSTEMIC',
  SEVERE = 'SEVERE'
}

export enum CrossReactivityLevel {
  NONE = 'NONE',
  LOW = 'LOW',
  MODERATE = 'MODERATE',
  PROBABLE = 'PROBABLE',
  HIGH = 'HIGH'
}

export enum Pathology {
  ALLERGIC_RHINITIS = 'ALLERGIC_RHINITIS',
  ASTHMA = 'ASTHMA',
  SEVERE_ASTHMA = 'SEVERE_ASTHMA',
  FOOD_ALLERGY = 'FOOD_ALLERGY',
  ANAPHYLAXIS = 'ANAPHYLAXIS',
  VENOM_ALLERGY = 'VENOM_ALLERGY',
  OCCUPATIONAL_ALLERGY = 'OCCUPATIONAL_ALLERGY'
}

export interface AllergenComponent {
  id: string;
  name: string;
  source: string;
  extract: string;
  category: AllergenCategory;
  type: AllergenType;
  symptoms: SymptomSeverity[];
  crossReactivity: CrossReactivityLevel;
  crossReactivityDetails: string;
  description: string;
  molecularFamily?: MolecularFamily;
  pathologies?: Pathology[];
}

export interface TestResult {
  allergenId: string;
  sIgE: number;
}

export interface PatientPanel {
  patientId: string;
  totalIgE: number;
  results: TestResult[];
}

export interface QualityFlag {
  code: string;
  severity: 'info' | 'warning' | 'error';
  message: string;
}

export interface Classification {
  allergenId: string;
  allergenName: string;
  source: string;
  sIgE: number;
  capClass: number;
  capLabel: string;
  sigeToTigeRatio: string;
  isPrimarySensitization: boolean;
}

export interface CrossReactivityCluster {
  molecularFamily: string;
  members: { allergenId: string; allergenName: string; sIgE: number }[];
  primarySource: string;
}

export interface SyndromeDetection {
  syndrome: string;
  detected: boolean;
  evidence: string[];
}

export interface RiskAssessment {
  overallRisk: 'low' | 'moderate' | 'high' | 'very-high';
  anaphylaxisRisk: boolean;
  aitEligible: boolean;
  aitRecommendations: string[];
}

export interface DiagnosticReport {
  patientId: string;
  classifications: Classification[];
  crossReactivityClusters: CrossReactivityCluster[];
  syndromes: SyndromeDetection[];
  riskAssessment: RiskAssessment;
}
