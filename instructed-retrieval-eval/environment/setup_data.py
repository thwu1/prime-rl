#!/usr/bin/env python3
"""Generate heterogeneous IR benchmark data for multi-task evaluation."""
import json
import os

DATA_DIR = "/app/data"

TASKS = {
    "biomedical": {
        "task_info": {
            "instruction": "Given a biomedical research question, retrieve peer-reviewed abstracts that provide direct experimental or clinical evidence addressing the question. Prioritize primary research findings over review summaries.",
            "domain": "healthcare",
            "relevance_scale": [0, 3],
            "relevance_type": "graded"
        },
        "queries": [
            {"qid": "bio_q1", "text": "mechanism of action of metformin in type 2 diabetes treatment"},
            {"qid": "bio_q2", "text": "early biomarkers for pancreatic cancer detection"},
            {"qid": "bio_q3", "text": "CRISPR Cas9 off-target effects and specificity improvement strategies"},
            {"qid": "bio_q4", "text": "immune checkpoint inhibitor efficacy in non-small cell lung cancer"},
        ],
        "corpus": [
            {"docid": "bio_d01", "text": "Metformin exerts its primary antidiabetic effect by suppressing hepatic glucose production through activation of AMP-activated protein kinase (AMPK). The drug improves peripheral insulin sensitivity in skeletal muscle and adipose tissue while reducing intestinal glucose absorption. Clinical trials demonstrate that metformin monotherapy reduces HbA1c by 1.0-1.5 percentage points in type 2 diabetes patients. The mechanism involves inhibition of mitochondrial complex I, leading to increased AMP:ATP ratio and subsequent AMPK phosphorylation."},
            {"docid": "bio_d02", "text": "Type 2 diabetes mellitus is a progressive metabolic disorder characterized by insulin resistance and beta-cell dysfunction. The disease affects over 400 million people globally. Standard treatment guidelines recommend lifestyle modification as first-line therapy, with pharmacological intervention initiated when glycemic targets are not achieved. Metformin remains the preferred initial oral agent due to its established efficacy and safety profile."},
            {"docid": "bio_d03", "text": "Gastrointestinal side effects are the most commonly reported adverse events with metformin therapy, affecting approximately 20-30 percent of patients. These include nausea, diarrhea, and abdominal cramping. Lactic acidosis is a rare but potentially fatal complication, occurring primarily in patients with renal impairment or hepatic dysfunction. Extended-release formulations have demonstrated improved gastrointestinal tolerability in randomized controlled trials."},
            {"docid": "bio_d04", "text": "Recent proteomic studies have identified CA19-9 combined with a panel of novel serum biomarkers including thrombospondin-2, MIC-1, and REG1A as promising candidates for early pancreatic cancer detection. In a prospective cohort of 500 patients, this multi-marker panel achieved sensitivity of 85 percent and specificity of 92 percent for stage I-II pancreatic ductal adenocarcinoma. Early detection biomarkers could significantly improve the currently dismal 5-year survival rate of under 10 percent."},
            {"docid": "bio_d05", "text": "Pancreatic cancer remains one of the most lethal malignancies with poor prognosis. Current treatment modalities include surgical resection for localized disease, gemcitabine-based chemotherapy, and emerging immunotherapy approaches. The FOLFIRINOX regimen has shown improved survival in metastatic cases. However, fewer than 20 percent of patients present with resectable disease at diagnosis, underscoring the critical need for improved early detection strategies."},
            {"docid": "bio_d06", "text": "Liquid biopsy approaches utilizing circulating tumor DNA (ctDNA) and exosomal microRNAs have shown promise as non-invasive cancer detection methods across multiple tumor types. In pancreatic cancer specifically, circulating exosomal glypican-1 was found elevated in precancerous and cancerous lesions. These biomarker approaches could complement traditional imaging for cancer screening in high-risk populations."},
            {"docid": "bio_d07", "text": "CRISPR-Cas9 genome editing suffers from off-target cleavage at genomic sites with sequence similarity to the guide RNA target. Whole-genome sequencing studies have revealed that off-target mutations can occur at frequencies ranging from 0.1 to 60 percent depending on the guide sequence. High-fidelity Cas9 variants including eSpCas9, SpCas9-HF1, and HypaCas9 have been engineered with point mutations in the REC3 domain to reduce off-target activity while maintaining on-target efficiency. Additionally, truncated guide RNAs of 17-18 nucleotides show improved specificity."},
            {"docid": "bio_d08", "text": "The CRISPR-Cas9 system has been adapted for diverse genome engineering applications beyond simple gene knockout. These include base editing for precise single-nucleotide changes, prime editing for targeted insertions and deletions, CRISPRi for transcriptional repression, and CRISPRa for gene activation. Delivery methods including ribonucleoprotein complexes, lipid nanoparticles, and adeno-associated viral vectors have been optimized for therapeutic applications in both ex vivo and in vivo settings."},
            {"docid": "bio_d09", "text": "Guide RNA design algorithms incorporating machine learning have substantially improved prediction of CRISPR on-target efficiency and off-target risk. Tools such as Cas-OFFinder, CRISPOR, and deep learning-based predictors enable researchers to select guide sequences with maximal specificity. Paired nickase strategies using Cas9 D10A with offset guide pairs reduce off-target mutagenesis by requiring two proximal cleavage events for a double-strand break. These computational and experimental strategies together address the specificity challenge in therapeutic gene editing."},
            {"docid": "bio_d10", "text": "Pembrolizumab and nivolumab, monoclonal antibodies targeting the PD-1 immune checkpoint receptor, have demonstrated significant improvements in overall survival for patients with advanced non-small cell lung cancer expressing PD-L1. The KEYNOTE-024 trial showed pembrolizumab monotherapy achieved median progression-free survival of 10.3 months versus 6.0 months for platinum-based chemotherapy in PD-L1 strong positive tumors. Combined PD-1 and CTLA-4 blockade with nivolumab plus ipilimumab has shown efficacy regardless of PD-L1 expression."},
            {"docid": "bio_d11", "text": "Non-small cell lung cancer accounts for approximately 85 percent of all lung cancers and encompasses adenocarcinoma, squamous cell carcinoma, and large cell carcinoma histological subtypes. TNM staging guides treatment decisions, with early-stage disease managed by surgical resection and adjuvant therapy. Molecular profiling for EGFR mutations, ALK rearrangements, and ROS1 fusions has enabled targeted therapy approaches that significantly improve outcomes in biomarker-selected populations."},
            {"docid": "bio_d12", "text": "Immune checkpoint inhibitors have transformed the treatment landscape for multiple solid tumors including melanoma, renal cell carcinoma, and lung cancer. Immune-related adverse events including pneumonitis, colitis, hepatitis, and endocrinopathies require careful monitoring and management. Combination strategies pairing checkpoint inhibitors with chemotherapy, radiation, or targeted agents are under active investigation in numerous clinical trials to expand efficacy across tumor types and patient populations."},
            {"docid": "bio_d13", "text": "Cardiovascular disease remains the leading cause of mortality globally, driven by atherosclerosis, hypertension, and metabolic syndrome. Novel therapeutic approaches targeting PCSK9, ANGPTL3, and lipoprotein(a) are in advanced clinical development. Wearable biosensor technology enables continuous cardiac monitoring and early arrhythmia detection in ambulatory settings."},
            {"docid": "bio_d14", "text": "Advances in regenerative medicine have enabled tissue engineering of cartilage, bone, and vascular grafts using stem cell-seeded scaffolds. Three-dimensional bioprinting technology allows precise spatial patterning of multiple cell types within hydrogel matrices. Clinical translation remains challenging due to vascularization requirements and immune rejection of allogeneic constructs."},
            {"docid": "bio_d15", "text": "The human gut microbiome encompasses trillions of microorganisms that influence host metabolism, immunity, and neurological function. Dysbiosis has been implicated in conditions ranging from inflammatory bowel disease to obesity. Fecal microbiota transplantation has shown remarkable efficacy for recurrent Clostridioides difficile infection, with cure rates exceeding 90 percent in clinical trials."},
        ],
        "qrels": [
            ("bio_q1", "bio_d01", 3), ("bio_q1", "bio_d02", 1), ("bio_q1", "bio_d03", 2),
            ("bio_q1", "bio_d13", 0), ("bio_q1", "bio_d14", 0), ("bio_q1", "bio_d15", 0),
            ("bio_q2", "bio_d04", 3), ("bio_q2", "bio_d05", 1), ("bio_q2", "bio_d06", 2),
            ("bio_q2", "bio_d01", 0), ("bio_q2", "bio_d13", 0), ("bio_q2", "bio_d14", 0),
            ("bio_q3", "bio_d07", 3), ("bio_q3", "bio_d08", 1), ("bio_q3", "bio_d09", 2),
            ("bio_q3", "bio_d01", 0), ("bio_q3", "bio_d04", 0), ("bio_q3", "bio_d13", 0),
            ("bio_q4", "bio_d10", 3), ("bio_q4", "bio_d11", 1), ("bio_q4", "bio_d12", 2),
            ("bio_q4", "bio_d01", 0), ("bio_q4", "bio_d07", 0), ("bio_q4", "bio_d13", 0),
        ],
        "runs": {
            "neural_a": [
                ("bio_q1", ["bio_d01","bio_d03","bio_d02","bio_d15","bio_d04","bio_d13","bio_d14","bio_d05","bio_d06","bio_d07"]),
                ("bio_q2", ["bio_d04","bio_d06","bio_d05","bio_d01","bio_d13","bio_d07","bio_d14","bio_d15","bio_d08","bio_d09"]),
                ("bio_q3", ["bio_d07","bio_d09","bio_d08","bio_d01","bio_d04","bio_d13","bio_d14","bio_d15","bio_d05","bio_d06"]),
                ("bio_q4", ["bio_d10","bio_d12","bio_d11","bio_d01","bio_d07","bio_d13","bio_d14","bio_d15","bio_d04","bio_d05"]),
            ],
            "neural_b": [
                ("bio_q1", ["bio_d03","bio_d01","bio_d15","bio_d02","bio_d14","bio_d04","bio_d13","bio_d05","bio_d06","bio_d07"]),
                ("bio_q2", ["bio_d06","bio_d05","bio_d04","bio_d13","bio_d01","bio_d14","bio_d07","bio_d15","bio_d09","bio_d08"]),
                ("bio_q3", ["bio_d09","bio_d08","bio_d07","bio_d04","bio_d01","bio_d14","bio_d13","bio_d15","bio_d06","bio_d05"]),
                ("bio_q4", ["bio_d12","bio_d11","bio_d10","bio_d07","bio_d01","bio_d14","bio_d13","bio_d15","bio_d05","bio_d04"]),
            ],
        },
    },
    "legal": {
        "task_info": {
            "instruction": "Retrieve court opinions, statutes, and legal memoranda that establish binding or persuasive precedent directly applicable to the legal issue described in the query.",
            "domain": "law",
            "relevance_scale": [0, 1],
            "relevance_type": "binary"
        },
        "queries": [
            {"qid": "law_q1", "text": "product liability for autonomous vehicle accidents manufacturer responsibility"},
            {"qid": "law_q2", "text": "fourth amendment digital privacy warrantless cell phone search"},
            {"qid": "law_q3", "text": "employment discrimination disparate impact burden of proof Title VII"},
            {"qid": "law_q4", "text": "patent eligibility abstract ideas software under Alice framework"},
        ],
        "corpus": [
            {"docid": "law_d01", "text": "In Martinez v. AutoDrive Corp. (2024), the Ninth Circuit held that manufacturers of Level 4 autonomous vehicles bear strict product liability for accidents caused by defects in self-driving software. The court reasoned that consumers cannot meaningfully inspect algorithmic decision-making, and the manufacturer is best positioned to ensure vehicle safety. This ruling extended traditional product liability principles to autonomous vehicle technology."},
            {"docid": "law_d02", "text": "The Restatement (Third) of Torts establishes that a product is defective in design when the foreseeable risks of harm could have been reduced by adoption of a reasonable alternative design. Section 402A strict liability applies when the product reaches the consumer without substantial change from the condition in which it was sold. Manufacturers bear responsibility regardless of the exercise of reasonable care."},
            {"docid": "law_d03", "text": "State legislatures have adopted varied regulatory frameworks for autonomous vehicle testing and deployment on public roads. California requires manufacturers to report all disengagement events and collisions involving autonomous test vehicles. Arizona adopted a more permissive approach allowing testing without prior regulatory approval, attracting significant industry investment."},
            {"docid": "law_d04", "text": "In Carpenter v. United States, 585 U.S. 296 (2018), the Supreme Court held that accessing historical cell-site location information constitutes a Fourth Amendment search requiring a warrant supported by probable cause. Chief Justice Roberts, writing for the majority, emphasized that cell phone location data provides an intimate window into a person's life, revealing familial, political, professional, religious, and sexual associations."},
            {"docid": "law_d05", "text": "Riley v. California, 573 U.S. 373 (2014), established that police generally may not search digital information on a cell phone seized incident to arrest without first obtaining a warrant. The Court unanimously held that digital data on cell phones differs quantitatively and qualitatively from physical objects, given the immense storage capacity and pervasive personal information contained on modern smartphones."},
            {"docid": "law_d06", "text": "The Electronic Communications Privacy Act of 1986 established statutory protections for electronic communications including email, telephone conversations, and electronically stored data. The Stored Communications Act, a component of ECPA, governs law enforcement access to stored electronic communications held by third-party service providers. Courts have increasingly found portions of ECPA outdated given technological advances."},
            {"docid": "law_d07", "text": "Under Griggs v. Duke Power Co., 401 U.S. 424 (1971), the Supreme Court recognized disparate impact as a cognizable theory of employment discrimination under Title VII. An employer's facially neutral practice that disproportionately excludes members of a protected class is unlawful unless the employer demonstrates the practice is job related and consistent with business necessity. The burden then shifts to the plaintiff to show an alternative practice with less discriminatory effect."},
            {"docid": "law_d08", "text": "The Civil Rights Act of 1991 codified the disparate impact framework, establishing that a complaining party must demonstrate that a respondent uses a particular employment practice causing disparate impact and that the respondent fails to demonstrate business necessity. Section 703(k) of Title VII as amended allocates burdens of proof in disparate impact cases and permits challenges to the validity of employer justifications."},
            {"docid": "law_d09", "text": "Federal employment law prohibits workplace harassment based on race, color, religion, sex, national origin, age, disability, and genetic information. The Equal Employment Opportunity Commission processes approximately 70,000 charges of workplace discrimination annually. Employer liability for supervisor harassment was clarified in Burlington Industries v. Ellerth and Faragher v. City of Boca Raton."},
            {"docid": "law_d10", "text": "In Alice Corp. v. CLS Bank International, 573 U.S. 208 (2014), the Supreme Court established a two-step framework for determining patent eligibility under 35 U.S.C. Section 101. First, the court determines whether the claims are directed to a patent-ineligible concept such as an abstract idea. Second, if so, the court examines whether the claim elements transform the nature of the claim into a patent-eligible application through an inventive concept."},
            {"docid": "law_d11", "text": "The Federal Circuit has applied Alice to invalidate numerous software patents on eligibility grounds. In Enfish v. Microsoft, the court held that claims directed to a specific improvement to computer functionality are not abstract. The subsequent decision in Berkheimer v. HP established that whether claim limitations represent well-understood, routine, and conventional activity is a factual question inappropriate for resolution on a motion to dismiss."},
            {"docid": "law_d12", "text": "International trade law governs the commercial exchange of goods and services across national borders. The World Trade Organization administers multilateral trade agreements and provides a dispute resolution mechanism for member nations. Tariff classifications under the Harmonized System determine applicable duty rates for imported merchandise."},
            {"docid": "law_d13", "text": "Environmental regulatory compliance requires industrial facilities to obtain permits under the Clean Air Act and Clean Water Act. The Environmental Protection Agency sets National Ambient Air Quality Standards for criteria pollutants. State environmental agencies typically administer federal programs through delegation agreements."},
            {"docid": "law_d14", "text": "Bankruptcy law under Title 11 of the United States Code provides mechanisms for debt relief including Chapter 7 liquidation and Chapter 11 reorganization. The automatic stay provision halts collection actions upon filing. Secured creditors retain liens on collateral subject to adequate protection requirements."},
            {"docid": "law_d15", "text": "Immigration law determines the conditions under which foreign nationals may enter, reside, and work in the United States. The Immigration and Nationality Act establishes categories of admission including family-based, employment-based, and diversity visa programs. Removal proceedings are conducted before immigration judges within the Executive Office for Immigration Review."},
        ],
        "qrels": [
            ("law_q1", "law_d01", 1), ("law_q1", "law_d02", 1), ("law_q1", "law_d03", 0),
            ("law_q1", "law_d12", 0), ("law_q1", "law_d13", 0), ("law_q1", "law_d14", 0),
            ("law_q2", "law_d04", 1), ("law_q2", "law_d05", 1), ("law_q2", "law_d06", 1),
            ("law_q2", "law_d01", 0), ("law_q2", "law_d12", 0), ("law_q2", "law_d13", 0),
            ("law_q3", "law_d07", 1), ("law_q3", "law_d08", 1), ("law_q3", "law_d09", 0),
            ("law_q3", "law_d01", 0), ("law_q3", "law_d12", 0), ("law_q3", "law_d13", 0),
            ("law_q4", "law_d10", 1), ("law_q4", "law_d11", 1), ("law_q4", "law_d12", 0),
            ("law_q4", "law_d01", 0), ("law_q4", "law_d13", 0), ("law_q4", "law_d14", 0),
        ],
        "runs": {
            "neural_a": [
                ("law_q1", ["law_d01","law_d02","law_d03","law_d12","law_d13","law_d14","law_d15","law_d04","law_d05","law_d06"]),
                ("law_q2", ["law_d04","law_d05","law_d06","law_d01","law_d12","law_d13","law_d14","law_d15","law_d07","law_d08"]),
                ("law_q3", ["law_d07","law_d08","law_d09","law_d01","law_d12","law_d13","law_d14","law_d15","law_d04","law_d05"]),
                ("law_q4", ["law_d10","law_d11","law_d12","law_d01","law_d13","law_d14","law_d15","law_d04","law_d05","law_d06"]),
            ],
            "neural_b": [
                ("law_q1", ["law_d02","law_d03","law_d01","law_d13","law_d12","law_d14","law_d15","law_d05","law_d04","law_d06"]),
                ("law_q2", ["law_d06","law_d04","law_d01","law_d05","law_d13","law_d12","law_d14","law_d15","law_d08","law_d07"]),
                ("law_q3", ["law_d09","law_d07","law_d08","law_d12","law_d01","law_d14","law_d13","law_d15","law_d05","law_d04"]),
                ("law_q4", ["law_d11","law_d12","law_d10","law_d13","law_d01","law_d15","law_d14","law_d05","law_d04","law_d06"]),
            ],
        },
    },
    "factcheck": {
        "task_info": {
            "instruction": "Retrieve news articles, reference documents, and verified factual sources that provide evidence to support or refute the given factual claim. Focus on primary sources with verifiable data.",
            "domain": "journalism",
            "relevance_scale": [0, 2],
            "relevance_type": "graded"
        },
        "queries": [
            {"qid": "fc_q1", "text": "global average temperature has risen by more than 1 degree Celsius since pre-industrial levels"},
            {"qid": "fc_q2", "text": "the Great Wall of China is visible from space with the naked eye"},
            {"qid": "fc_q3", "text": "humans use only 10 percent of their brain capacity"},
            {"qid": "fc_q4", "text": "lightning never strikes the same place twice"},
        ],
        "corpus": [
            {"docid": "fc_d01", "text": "The World Meteorological Organization confirmed that global mean surface temperature in 2023 was approximately 1.45 degrees Celsius above the pre-industrial 1850-1900 baseline. The Intergovernmental Panel on Climate Change Sixth Assessment Report documented that human-caused greenhouse gas emissions have driven an observed warming of 1.1 degrees Celsius between 1850-1900 and 2011-2020. Multiple independent temperature datasets from NASA GISS, NOAA, HadCRUT, and Berkeley Earth all corroborate this warming trend."},
            {"docid": "fc_d02", "text": "Ice core records from Antarctica and Greenland provide paleoclimate evidence spanning hundreds of thousands of years. Analysis of trapped air bubbles reveals pre-industrial atmospheric CO2 concentrations of approximately 280 parts per million compared to current levels exceeding 420 ppm. Isotopic analysis of these records supports the attribution of recent warming to anthropogenic greenhouse gas emissions."},
            {"docid": "fc_d03", "text": "Climate models project continued warming under all emission scenarios assessed by the IPCC. Under the high-emission SSP5-8.5 pathway, global temperature could rise by 3.3 to 5.7 degrees Celsius by 2100 relative to pre-industrial levels. Even under the most ambitious mitigation scenario SSP1-1.9, warming is projected to temporarily exceed 1.5 degrees before declining through carbon dioxide removal."},
            {"docid": "fc_d04", "text": "NASA astronaut observations and high-resolution satellite imagery have consistently demonstrated that the Great Wall of China is not visible from low Earth orbit with the unaided eye. The wall averages only 4 to 5 meters in width, which falls below the angular resolution limit of human vision at orbital altitudes of 350 to 400 kilometers. Astronaut William Pogue reported that he thought he saw the wall but later discovered he was looking at the Grand Canal."},
            {"docid": "fc_d05", "text": "The Great Wall of China extends approximately 21,196 kilometers including all branches and sections built over multiple dynasties. Construction began in the 7th century BCE and continued through the Ming Dynasty. The most well-preserved sections near Beijing attract millions of tourists annually. Despite its enormous length, the wall is too narrow relative to orbital viewing distances to be resolved by the human eye without optical magnification."},
            {"docid": "fc_d06", "text": "From the International Space Station at an altitude of approximately 400 kilometers, many human-made structures are visible including airports, highways, cities, and large dams. However, linear features narrower than about 100 meters generally cannot be distinguished without telescopic equipment. The Great Wall, while extensive in length, does not meet this width threshold."},
            {"docid": "fc_d07", "text": "Modern neuroscience research using functional magnetic resonance imaging and positron emission tomography has conclusively demonstrated that humans utilize virtually all regions of the brain. Different tasks activate different neural circuits, and even during sleep, brain regions remain metabolically active. The 10 percent myth likely originated from misinterpretations of early neuroscience research on localized brain functions and glial cell counts."},
            {"docid": "fc_d08", "text": "Brain lesion studies consistently show that damage to almost any brain region produces measurable functional deficits. Neurodegenerative diseases like Alzheimer's progressively destroy brain tissue, with profound cognitive consequences even when affecting relatively small portions of total brain volume. If 90 percent of the brain were truly unused, such damage would be inconsequential, contradicting clinical observations."},
            {"docid": "fc_d09", "text": "Neuroscience textbooks explain that the brain accounts for approximately 2 percent of body weight but consumes roughly 20 percent of the body's energy. This high metabolic cost would be evolutionarily disadvantageous if most brain tissue served no function. Neural plasticity allows reassignment of cortical areas after injury, but this reflects reorganization of active tissue rather than recruitment of previously dormant regions."},
            {"docid": "fc_d10", "text": "Lightning frequently strikes the same location repeatedly, particularly tall structures and geographical features. The Empire State Building in New York City is struck approximately 20 to 25 times per year. Lightning rods function precisely because lightning preferentially strikes elevated conductive points. Analysis of lightning strike data from the National Lightning Detection Network confirms that certain locations experience dramatically higher strike frequencies."},
            {"docid": "fc_d11", "text": "A single thunderstorm can produce thousands of lightning discharges. Cloud-to-ground lightning follows ionized channels through the atmosphere, and return strokes frequently follow previously established pathways within the same flash event. Research on triggered lightning at the International Center for Lightning Research in Florida demonstrates that rockets trailing grounded wires reliably initiate lightning strikes at the same location repeatedly."},
            {"docid": "fc_d12", "text": "Severe weather forecasting relies on Doppler radar networks, satellite imagery, and numerical weather prediction models to identify conditions favorable for thunderstorm development. The Storm Prediction Center issues convective outlooks categorizing risk levels for tornado and severe thunderstorm occurrence across the continental United States."},
            {"docid": "fc_d13", "text": "Renewable energy sources including solar photovoltaics, onshore and offshore wind, and hydroelectric power have experienced dramatic cost reductions over the past decade. Global renewable electricity capacity additions exceeded fossil fuel additions for the first time. Energy storage technologies including lithium-ion batteries and pumped hydro are critical for managing intermittency of wind and solar generation."},
            {"docid": "fc_d14", "text": "Ocean acidification results from absorption of atmospheric carbon dioxide by seawater, reducing ocean pH. Coral reef ecosystems are particularly vulnerable, with bleaching events increasing in frequency and severity. Marine biodiversity faces compounding pressures from warming temperatures, acidification, deoxygenation, and overfishing."},
            {"docid": "fc_d15", "text": "The global population reached 8 billion in November 2022 according to United Nations estimates. Demographic projections suggest the population will peak at approximately 10.4 billion around 2080 before gradually declining. Fertility rates have fallen below replacement level in most developed nations, while sub-Saharan Africa continues to experience the highest population growth rates."},
        ],
        "qrels": [
            ("fc_q1", "fc_d01", 2), ("fc_q1", "fc_d02", 1), ("fc_q1", "fc_d03", 1),
            ("fc_q1", "fc_d13", 0), ("fc_q1", "fc_d14", 0), ("fc_q1", "fc_d15", 0),
            ("fc_q2", "fc_d04", 2), ("fc_q2", "fc_d05", 1), ("fc_q2", "fc_d06", 1),
            ("fc_q2", "fc_d01", 0), ("fc_q2", "fc_d13", 0), ("fc_q2", "fc_d14", 0),
            ("fc_q3", "fc_d07", 2), ("fc_q3", "fc_d08", 1), ("fc_q3", "fc_d09", 1),
            ("fc_q3", "fc_d01", 0), ("fc_q3", "fc_d04", 0), ("fc_q3", "fc_d13", 0),
            ("fc_q4", "fc_d10", 2), ("fc_q4", "fc_d11", 1), ("fc_q4", "fc_d12", 0),
            ("fc_q4", "fc_d01", 0), ("fc_q4", "fc_d04", 0), ("fc_q4", "fc_d13", 0),
        ],
        "runs": {
            "neural_a": [
                ("fc_q1", ["fc_d01","fc_d02","fc_d03","fc_d14","fc_d13","fc_d15","fc_d04","fc_d05","fc_d06","fc_d07"]),
                ("fc_q2", ["fc_d04","fc_d05","fc_d06","fc_d01","fc_d13","fc_d14","fc_d15","fc_d07","fc_d08","fc_d09"]),
                ("fc_q3", ["fc_d07","fc_d08","fc_d09","fc_d01","fc_d04","fc_d13","fc_d14","fc_d15","fc_d10","fc_d11"]),
                ("fc_q4", ["fc_d10","fc_d11","fc_d12","fc_d01","fc_d04","fc_d13","fc_d14","fc_d15","fc_d07","fc_d08"]),
            ],
            "neural_b": [
                ("fc_q1", ["fc_d03","fc_d01","fc_d14","fc_d02","fc_d13","fc_d15","fc_d05","fc_d04","fc_d06","fc_d07"]),
                ("fc_q2", ["fc_d05","fc_d06","fc_d04","fc_d13","fc_d01","fc_d15","fc_d14","fc_d08","fc_d07","fc_d09"]),
                ("fc_q3", ["fc_d08","fc_d09","fc_d07","fc_d04","fc_d01","fc_d14","fc_d13","fc_d15","fc_d11","fc_d10"]),
                ("fc_q4", ["fc_d11","fc_d12","fc_d10","fc_d04","fc_d01","fc_d14","fc_d13","fc_d15","fc_d08","fc_d07"]),
            ],
        },
    },
}


def write_task(task_name, task_data):
    """Write all files for a single IR task."""
    task_dir = os.path.join(DATA_DIR, task_name)
    os.makedirs(os.path.join(task_dir, "runs"), exist_ok=True)

    # task_info.json
    with open(os.path.join(task_dir, "task_info.json"), "w") as f:
        json.dump(task_data["task_info"], f, indent=2)

    # queries.jsonl
    with open(os.path.join(task_dir, "queries.jsonl"), "w") as f:
        for q in task_data["queries"]:
            f.write(json.dumps(q) + "\n")

    # corpus.jsonl
    with open(os.path.join(task_dir, "corpus.jsonl"), "w") as f:
        for doc in task_data["corpus"]:
            f.write(json.dumps(doc) + "\n")

    # qrels.tsv (TREC format: qid 0 docid relevance)
    with open(os.path.join(task_dir, "qrels.tsv"), "w") as f:
        for qid, docid, rel in task_data["qrels"]:
            f.write(f"{qid}\t0\t{docid}\t{rel}\n")

    # Run files (TREC format: qid Q0 docid rank score run_name)
    for run_name, run_data in task_data["runs"].items():
        with open(os.path.join(task_dir, "runs", f"{run_name}.tsv"), "w") as f:
            for qid, doc_ranking in run_data:
                for rank, docid in enumerate(doc_ranking, 1):
                    score = 1000 - rank * 10  # Descending scores
                    f.write(f"{qid}\tQ0\t{docid}\t{rank}\t{score}\t{run_name}\n")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    for task_name, task_data in TASKS.items():
        write_task(task_name, task_data)
    print(f"Generated data for {len(TASKS)} tasks in {DATA_DIR}")


if __name__ == "__main__":
    main()
