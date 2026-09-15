
import {
  AllergenComponent, AllergenCategory, AllergenType,
  SymptomSeverity, CrossReactivityLevel, MolecularFamily, Pathology
} from './types';

export const allergenDatabase: AllergenComponent[] = [
  // === TREE POLLENS ===
  {
    id: 't215', name: 'rBet v 1', source: 'Birch', extract: 'Birch (t3)',
    category: AllergenCategory.TREE_POLLENS, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.LOCAL, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.PROBABLE,
    crossReactivityDetails: 'Cross-reactivity with other PR-10 allergens (apple, hazelnut, celery)',
    description: 'Marker of primary sensitization to birch. Pollen-food allergy syndrome.',
    molecularFamily: MolecularFamily.PR10,
    pathologies: [Pathology.ALLERGIC_RHINITIS]
  },
  {
    id: 't216', name: 'rBet v 2', source: 'Birch', extract: 'Birch (t3)',
    category: AllergenCategory.TREE_POLLENS, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.LOCAL, SymptomSeverity.ASYMPTOMATIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Profilin panallergen. Cross-reactivity with numerous pollens and plant foods.',
    description: 'Minor cross-reactive allergen (profilin).',
    molecularFamily: MolecularFamily.PROFILINS
  },

  // === GRASS POLLENS ===
  {
    id: 'g205', name: 'rPhl p 1', source: 'Timothy grass', extract: 'Timothy grass (g6)',
    category: AllergenCategory.GRASS_POLLENS, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.LOW,
    crossReactivityDetails: 'Specific to group 1 grasses.',
    description: 'Major and specific allergen of timothy grass. Indication for AIT.',
    pathologies: [Pathology.ALLERGIC_RHINITIS]
  },
  {
    id: 'g212', name: 'rPhl p 12', source: 'Timothy grass', extract: 'Timothy grass (g6)',
    category: AllergenCategory.GRASS_POLLENS, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.LOCAL],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Profilin panallergen.',
    description: 'Minor allergen (profilin) indicating complex sensitization.',
    molecularFamily: MolecularFamily.PROFILINS
  },

  // === WEED POLLENS ===
  {
    id: 'w233', name: 'nArt v 3', source: 'Mugwort', extract: 'Mugwort (w6)',
    category: AllergenCategory.WEED_POLLENS, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'LTP. Cross-reactivity with other pollen and food LTPs.',
    description: 'LTP-type allergen, associated with LTP syndrome.',
    molecularFamily: MolecularFamily.LTP
  },

  // === ANIMALS ===
  {
    id: 'e94', name: 'rFel d 1', source: 'Cat', extract: 'Cat (e1)',
    category: AllergenCategory.ANIMALS, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.NONE,
    crossReactivityDetails: 'Cat specific. Uteroglobin.',
    description: 'Major cat allergen. Indication for AIT. Predictive marker of cat allergy.',
    pathologies: [Pathology.ASTHMA, Pathology.SEVERE_ASTHMA]
  },
  {
    id: 'e220', name: 'rFel d 2', source: 'Cat', extract: 'Cat (e1)',
    category: AllergenCategory.ANIMALS, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.LOCAL],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Serum albumin. Cross-reactivity with dog, horse, pork.',
    description: 'Minor cat allergen. Pork-cat syndrome marker.',
    molecularFamily: MolecularFamily.SERUM_ALBUMINS
  },
  {
    id: 'e101', name: 'rCan f 1', source: 'Dog', extract: 'Dog (e5)',
    category: AllergenCategory.ANIMALS, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.MODERATE,
    crossReactivityDetails: 'Lipocalin.',
    description: 'Major dog allergen, marker of primary sensitization.',
    molecularFamily: MolecularFamily.LIPOCALINS,
    pathologies: [Pathology.ASTHMA]
  },
  {
    id: 'e221', name: 'nCan f 3', source: 'Dog', extract: 'Dog (e5)',
    category: AllergenCategory.ANIMALS, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.LOCAL],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Serum albumin. Cross-reactivity with cat, beef.',
    description: 'Minor dog allergen. Cross-reactivity marker.',
    molecularFamily: MolecularFamily.SERUM_ALBUMINS
  },

  // === MITES ===
  {
    id: 'd202', name: 'rDer p 1', source: 'House dust mite (D. pteronyssinus)',
    extract: 'D. ptero (d1)',
    category: AllergenCategory.MITES, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SYSTEMIC, SymptomSeverity.SEVERE],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Cysteine protease. Mite specific.',
    description: 'Major marker of mite sensitization. AIT indication.',
    pathologies: [Pathology.ASTHMA, Pathology.SEVERE_ASTHMA]
  },
  {
    id: 'd205', name: 'rDer p 10', source: 'Mite', extract: 'D. ptero (d1)',
    category: AllergenCategory.MITES, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Tropomyosin. Invertebrate panallergen.',
    description: 'Cross-reactivity marker with crustaceans.',
    molecularFamily: MolecularFamily.TROPOMYOSINS
  },

  // === MOLDS ===
  {
    id: 'm229', name: 'rAlt a 1', source: 'Alternaria alternata',
    extract: 'Alternaria (m6)',
    category: AllergenCategory.MOLDS, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE],
    crossReactivity: CrossReactivityLevel.LOW,
    crossReactivityDetails: 'Specific to Alternaria.',
    description: 'Major mold allergen. Risk factor for severe asthma. AIT indication.',
    pathologies: [Pathology.ASTHMA, Pathology.SEVERE_ASTHMA]
  },

  // === VENOMS ===
  {
    id: 'i208', name: 'rApi m 1', source: 'Honey bee', extract: 'Honey bee (i1)',
    category: AllergenCategory.VENOMS, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.LOW,
    crossReactivityDetails: 'Phospholipase A2. Bee specific.',
    description: 'Major bee venom allergen. Essential for VIT.',
    pathologies: [Pathology.VENOM_ALLERGY]
  },
  {
    id: 'i209', name: 'rVes v 5', source: 'Common wasp', extract: 'Common wasp (i3)',
    category: AllergenCategory.VENOMS, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.LOW,
    crossReactivityDetails: 'Antigen 5. Wasp specific.',
    description: 'Major wasp venom allergen.',
    pathologies: [Pathology.VENOM_ALLERGY]
  },

  // === FOOD: PEANUT ===
  {
    id: 'f422', name: 'rAra h 1', source: 'Peanut', extract: 'Peanut (f13)',
    category: AllergenCategory.FOOD_PEANUT, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.LOW,
    crossReactivityDetails: '7S storage protein, stable.',
    description: 'Risk marker for systemic reactions to peanut.',
    molecularFamily: MolecularFamily.STORAGE_PROTEINS,
    pathologies: [Pathology.FOOD_ALLERGY]
  },
  {
    id: 'f423', name: 'rAra h 2', source: 'Peanut', extract: 'Peanut (f13)',
    category: AllergenCategory.FOOD_PEANUT, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.LOW,
    crossReactivityDetails: '2S albumin storage protein, very stable.',
    description: 'High-risk marker for severe systemic reactions. Stable to heat and digestion.',
    molecularFamily: MolecularFamily.STORAGE_PROTEINS,
    pathologies: [Pathology.ANAPHYLAXIS, Pathology.FOOD_ALLERGY]
  },
  {
    id: 'f424', name: 'rAra h 3', source: 'Peanut', extract: 'Peanut (f13)',
    category: AllergenCategory.FOOD_PEANUT, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SYSTEMIC, SymptomSeverity.SEVERE],
    crossReactivity: CrossReactivityLevel.LOW,
    crossReactivityDetails: '11S storage protein, stable.',
    description: 'Risk marker for systemic reactions to peanut.',
    molecularFamily: MolecularFamily.STORAGE_PROTEINS,
    pathologies: [Pathology.FOOD_ALLERGY]
  },
  {
    id: 'f352', name: 'rAra h 8', source: 'Peanut', extract: 'Peanut (f13)',
    category: AllergenCategory.FOOD_PEANUT, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.LOCAL, SymptomSeverity.ASYMPTOMATIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'PR-10. Cross-reactivity with birch pollen (Bet v 1).',
    description: 'Oral allergy syndrome marker. Low risk of systemic reaction. Heat labile.',
    molecularFamily: MolecularFamily.PR10
  },
  {
    id: 'f427', name: 'rAra h 9', source: 'Peanut', extract: 'Peanut (f13)',
    category: AllergenCategory.FOOD_PEANUT, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.SYSTEMIC, SymptomSeverity.LOCAL],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'LTP. Cross-reactivity with other food LTPs.',
    description: 'Cross-reactivity marker (LTP). Heat stable.',
    molecularFamily: MolecularFamily.LTP
  },

  // === FOOD: TREE NUTS ===
  {
    id: 'f428', name: 'rCor a 1', source: 'Hazelnut', extract: 'Hazelnut (f17)',
    category: AllergenCategory.FOOD_TREE_NUTS, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.LOCAL, SymptomSeverity.ASYMPTOMATIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'PR-10. High cross-reactivity with birch pollen (Bet v 1).',
    description: 'OAS marker, heat labile. Low risk of systemic reaction.',
    molecularFamily: MolecularFamily.PR10,
    pathologies: [Pathology.FOOD_ALLERGY]
  },
  {
    id: 'f425', name: 'rCor a 8', source: 'Hazelnut', extract: 'Hazelnut (f17)',
    category: AllergenCategory.FOOD_TREE_NUTS, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.SYSTEMIC, SymptomSeverity.LOCAL],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'LTP. Cross-reactivity with peach LTP.',
    description: 'LTP marker, especially Mediterranean.',
    molecularFamily: MolecularFamily.LTP,
    pathologies: [Pathology.FOOD_ALLERGY]
  },
  {
    id: 'f439', name: 'rCor a 14', source: 'Hazelnut', extract: 'Hazelnut (f17)',
    category: AllergenCategory.FOOD_TREE_NUTS, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.LOW,
    crossReactivityDetails: '2S albumin storage protein, heat stable.',
    description: 'Marker of primary hazelnut allergy, severe systemic reactions.',
    molecularFamily: MolecularFamily.STORAGE_PROTEINS,
    pathologies: [Pathology.ANAPHYLAXIS, Pathology.FOOD_ALLERGY]
  },
  {
    id: 'f441', name: 'rJug r 1', source: 'Walnut', extract: 'Walnut (f256)',
    category: AllergenCategory.FOOD_TREE_NUTS, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: '2S albumin. Cross-reactivity with pecan.',
    description: 'High-risk marker for walnut and pecan.',
    molecularFamily: MolecularFamily.STORAGE_PROTEINS
  },

  // === FOOD: PEACH ===
  {
    id: 'f420', name: 'rPru p 3', source: 'Peach', extract: 'Peach (f95)',
    category: AllergenCategory.FOOD_PEACH, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'LTP. Risk marker for systemic reactions.',
    description: 'Major peach allergen, LTP. Heat stable, severe reactions.',
    molecularFamily: MolecularFamily.LTP,
    pathologies: [Pathology.ANAPHYLAXIS, Pathology.FOOD_ALLERGY]
  },
  {
    id: 'f454', name: 'rPru p 7', source: 'Peach', extract: 'Peach (f95)',
    category: AllergenCategory.FOOD_PEACH, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.PROBABLE,
    crossReactivityDetails: 'GRP linked to severe fruit allergy and cypress pollen.',
    description: 'Gibberellin-regulated protein marker for severe fruit allergy.',
    molecularFamily: MolecularFamily.GRP
  },

  // === FOOD: FRUITS/VEGETABLES ===
  {
    id: 'f434', name: 'rMal d 1', source: 'Apple', extract: 'Apple (f49)',
    category: AllergenCategory.FOOD_FRUITS_VEGETABLES, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.LOCAL],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'PR-10. Cross-reacts with Bet v 1 from birch.',
    description: 'Major apple allergen for oral allergy syndrome. Heat labile.',
    molecularFamily: MolecularFamily.PR10
  },

  // === FOOD: SOY ===
  {
    id: 'f353', name: 'rGly m 4', source: 'Soy', extract: 'Soy (f14)',
    category: AllergenCategory.FOOD_SOY, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.LOCAL, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'PR-10. Cross-reactivity with birch pollen.',
    description: 'OAS marker in birch pollen allergic patients. Heat labile.',
    molecularFamily: MolecularFamily.PR10,
    pathologies: [Pathology.FOOD_ALLERGY]
  },

  // === FOOD: SESAME ===
  {
    id: 'f449', name: 'rSes i 1', source: 'Sesame', extract: 'Sesame (f10)',
    category: AllergenCategory.FOOD_SESAME, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.LOW,
    crossReactivityDetails: '2S albumin storage protein.',
    description: 'Major sesame allergen, primary allergy marker.',
    molecularFamily: MolecularFamily.STORAGE_PROTEINS,
    pathologies: [Pathology.ANAPHYLAXIS, Pathology.FOOD_ALLERGY]
  },

  // === FOOD: SHELLFISH ===
  {
    id: 'f351', name: 'rPen a 1', source: 'Shrimp', extract: 'Shrimp (f24)',
    category: AllergenCategory.FOOD_SHELLFISH, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Tropomyosin. Invertebrate panallergen.',
    description: 'Major shrimp allergen, heat-stable.',
    molecularFamily: MolecularFamily.TROPOMYOSINS,
    pathologies: [Pathology.ANAPHYLAXIS, Pathology.FOOD_ALLERGY]
  },

  // === FOOD: EGG ===
  {
    id: 'f75', name: 'nGal d 5', source: 'Egg yolk', extract: 'Egg yolk (f75)',
    category: AllergenCategory.FOOD_EGG, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Livetin/alpha-livetin. Cross-reactivity with bird serum albumins.',
    description: 'Marker for bird-egg syndrome.',
    molecularFamily: MolecularFamily.SERUM_ALBUMINS
  },

  // === FOOD: MILK ===
  {
    id: 'e204', name: 'nBos d 6', source: "Cow's milk", extract: "Cow's milk (f2)",
    category: AllergenCategory.FOOD_MILK, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.LOCAL, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Bovine serum albumin. Cross-reactivity with beef and other albumins.',
    description: 'Minor milk allergen. Pork-cat syndrome cross-reactivity marker.',
    molecularFamily: MolecularFamily.SERUM_ALBUMINS
  },

  // === LATEX ===
  {
    id: 'k220', name: 'rHev b 6.02', source: 'Latex', extract: 'Latex (k82)',
    category: AllergenCategory.LATEX, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SYSTEMIC, SymptomSeverity.LOCAL],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Hevein. Associated with latex-food syndrome.',
    description: 'Major allergen in healthcare workers, latex-food syndrome marker.',
    pathologies: [Pathology.OCCUPATIONAL_ALLERGY]
  },

  // === FOOD: MEAT (Alpha-Gal) ===
  {
    id: 'o215', name: 'Alpha-Gal', source: 'Mammalian meat',
    extract: 'Pork (f26) / Beef (f27)',
    category: AllergenCategory.FOOD_MEAT, type: AllergenType.MAJOR,
    symptoms: [SymptomSeverity.SEVERE, SymptomSeverity.SYSTEMIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'Carbohydrate. Cross-reactivity among all non-primate mammalian meats.',
    description: 'Alpha-Gal Syndrome. Delayed allergic reactions to red meat after tick bite.'
  },

  // === CCD MARKER ===
  {
    id: 'o214', name: 'nMUXF3', source: 'CCD Marker', extract: 'CCD (o214)',
    category: AllergenCategory.CCD, type: AllergenType.MINOR,
    symptoms: [SymptomSeverity.ASYMPTOMATIC],
    crossReactivity: CrossReactivityLevel.HIGH,
    crossReactivityDetails: 'CCD marker. Often clinically irrelevant false positives.',
    description: 'Positivity indicates CCD sensitization causing false positives in IgE tests.'
  }
];
