
export enum AllergenType {
  MAJOR = "MAJOR",
  MINOR = "MINOR"
}

export enum SymptomSeverity {
  ASYMPTOMATIC = "ASYMPTOMATIC",
  LOCAL = "LOCAL",
  SYSTEMIC = "SYSTEMIC",
  SEVERE = "SEVERE"
}

export enum CrossReactivityLevel {
  NONE = "NONE",
  LOW = "LOW",
  MODERATE = "MODERATE",
  PROBABLE = "PROBABLE",
  HIGH = "HIGH"
}

export enum MolecularFamily {
  PR10 = "PR10",
  LTP = "LTP",
  PROFILINS = "PROFILINS",
  POLCALCINS = "POLCALCINS",
  SERUM_ALBUMINS = "SERUM_ALBUMINS",
  LIPOCALINS = "LIPOCALINS",
  STORAGE_PROTEINS = "STORAGE_PROTEINS",
  TROPOMYOSINS = "TROPOMYOSINS",
  PARVALBUMINS = "PARVALBUMINS",
  GRP = "GRP",
  TLP = "TLP"
}

export enum Classification {
  PRIMARY = "PRIMARY",
  CROSS_REACTIVE = "CROSS_REACTIVE",
  UNDETERMINED = "UNDETERMINED"
}

export enum RiskLevel {
  NEGLIGIBLE = "NEGLIGIBLE",
  LOW = "LOW",
  MODERATE = "MODERATE",
  HIGH = "HIGH",
  VERY_HIGH = "VERY_HIGH"
}

export interface Allergen {
  id: string;
  name: string;
  source: string;
  extract: string;
  category: string;
  type: AllergenType;
  symptoms: SymptomSeverity[];
  crossReactivityLevel: CrossReactivityLevel;
  crossReactivityDetails: string;
  description: string;
  molecularFamily?: MolecularFamily;
  pathologies?: string[];
}

export interface PatientPanel {
  patient_id: string;
  total_ige_kua_l: number;
  results: PanelResult[];
}

export interface PanelResult {
  allergen_id: string;
  sige_kua_l: number;
}

export interface AllergenResult {
  allergen_id: string;
  allergen_name: string;
  source: string;
  cap_class: number;
  sige_tige_ratio: number;
  classification: Classification;
  risk_level: RiskLevel;
  ait_eligible: boolean;
}

export interface DetectedSyndrome {
  name: string;
  involved_allergens: string[];
  evidence: string;
}

export interface DiagnosticReport {
  patient_id: string;
  allergen_results: AllergenResult[];
  detected_syndromes: DetectedSyndrome[];
  overall_risk: RiskLevel;
}
