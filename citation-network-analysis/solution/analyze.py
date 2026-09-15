"""

Legal Citation Forensics Audit Pipeline
"""

import json
import os
import re
from collections import defaultdict

from eyecite import get_citations, resolve_citations
from eyecite.models import (
    FullCaseCitation,
    ShortCaseCitation,
    SupraCitation,
    IdCitation,
)
from courts_db import find_court


CORPUS_DIR = "/app/corpus"
OUTPUT_PATH = "/app/report.json"

# ---------------------------------------------------------------------------
# Court header identification
# ---------------------------------------------------------------------------
COURT_HEADER_PATTERNS = [
    (r"SUPREME COURT OF THE UNITED STATES", "Supreme Court of the United States"),
    (r"UNITED STATES COURT OF APPEALS FOR THE SECOND CIRCUIT", "Court of Appeals for the Second Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE NINTH CIRCUIT", "Court of Appeals for the Ninth Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE FEDERAL CIRCUIT", "Court of Appeals for the Federal Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE SEVENTH CIRCUIT", "Court of Appeals for the Seventh Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE FIRST CIRCUIT", "Court of Appeals for the First Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE THIRD CIRCUIT", "Court of Appeals for the Third Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE FOURTH CIRCUIT", "Court of Appeals for the Fourth Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE FIFTH CIRCUIT", "Court of Appeals for the Fifth Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE SIXTH CIRCUIT", "Court of Appeals for the Sixth Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE EIGHTH CIRCUIT", "Court of Appeals for the Eighth Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE TENTH CIRCUIT", "Court of Appeals for the Tenth Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE ELEVENTH CIRCUIT", "Court of Appeals for the Eleventh Circuit"),
    (r"UNITED STATES COURT OF APPEALS FOR THE D\.?C\.? CIRCUIT", "Court of Appeals for the D.C. Circuit"),
]

# ---------------------------------------------------------------------------
# Court abbreviation mapping (parenthetical -> canonical CourtListener ID)
# ---------------------------------------------------------------------------
CIRCUIT_COURT_MAP = {
    "1st Cir.": "ca1", "2d Cir.": "ca2", "2nd Cir.": "ca2",
    "3d Cir.": "ca3", "3rd Cir.": "ca3", "4th Cir.": "ca4",
    "5th Cir.": "ca5", "6th Cir.": "ca6", "7th Cir.": "ca7",
    "8th Cir.": "ca8", "9th Cir.": "ca9", "10th Cir.": "ca10",
    "11th Cir.": "ca11", "D.C. Cir.": "cadc", "Fed. Cir.": "cafc",
}

SCOTUS_REPORTERS = {"U.S.", "S. Ct.", "S.Ct.", "L. Ed.", "L. Ed. 2d"}

# ---------------------------------------------------------------------------
# Doctrinal topic keywords for thread identification
# ---------------------------------------------------------------------------
TOPIC_KEYWORDS = {
    "title_vii_burden_shifting": [
        "discrimination", "title vii", "prima facie", "pretext",
        "burden", "protected class", "adverse employment",
        "employer", "disparate", "circumstantial evidence",
    ],
    "major_questions_doctrine": [
        "administrative agenc", "statutory authority", "major question",
        "congressional authorization", "deference", "regulatory authority",
        "bounds of authority", "clean air act", "clean power",
        "transformative", "enabling legislation",
    ],
    "section_230_immunity": [
        "section 230", "interactive computer", "publisher or speaker",
        "content provider", "editorial discretion", "third-party content",
        "communications decency", "platform", "algorithmic",
    ],
    "patent_claim_construction": [
        "claim construction", "patent claim", "specification",
        "prosecution history", "intrinsic evidence", "claim term",
        "customary meaning", "construing", "person of ordinary skill",
    ],
    "doctrine_of_equivalents": [
        "doctrine of equivalents", "function-way-result",
        "substantially the same", "prosecution history estoppel",
        "infringement under",
    ],
    "cwa_jurisdiction": [
        "clean water act", "navigable water", "waters of the united",
        "wetland", "significant nexus", "surface connection",
        "npdes", "discharge of pollutant", "point source",
    ],
}


def identify_court(text):
    """Identify the authoring court from the opinion header text."""
    header = text[:500]
    for pattern, query in COURT_HEADER_PATTERNS:
        if re.search(pattern, header, re.IGNORECASE):
            results = find_court(query)
            if results:
                return results[0]
    return "unknown"


def extract_full_case_triple(cite):
    """Extract [volume, reporter, page] from a FullCaseCitation."""
    return [
        cite.groups.get("volume", ""),
        cite.groups.get("reporter", ""),
        cite.groups.get("page", ""),
    ]


def get_cited_court(cite):
    """Determine the canonical court ID of the cited case from its reporter
    and parenthetical court attribution."""
    reporter = cite.groups.get("reporter", "")

    # SCOTUS reporters unambiguously identify the Supreme Court
    if reporter in SCOTUS_REPORTERS:
        return "scotus"

    # eyecite normalizes the parenthetical court to canonical IDs
    # (e.g., "ca2", "ca5", "cafc") in metadata.court
    if hasattr(cite, "metadata") and cite.metadata:
        court_id = getattr(cite.metadata, "court", "") or ""
        if court_id:
            return court_id

    return "unknown"


def is_binding_authority(citing_court, cited_court, reporter):
    """Determine whether a citation is binding precedent on the citing court."""
    # SCOTUS binds all federal courts
    if cited_court == "scotus":
        return True
    # Unpublished decisions (F. App'x / F.Appx) are never binding
    if "App" in reporter:
        return False
    # Same-circuit published precedent is binding
    if citing_court == cited_court:
        return True
    # Everything else (sister circuits, district courts) is persuasive
    return False


def score_topic(text_lower, keywords):
    """Count how many topic keywords appear in the text."""
    return sum(1 for kw in keywords if kw in text_lower)


# ---------------------------------------------------------------------------
# Doctrinal thread identification
# ---------------------------------------------------------------------------
def identify_doctrinal_threads(doc_data):
    """Identify doctrinal threads by analyzing paragraph-level context
    around citations across the corpus."""
    threads = defaultdict(lambda: {"cases": set(), "documents": set()})

    for filename, data in doc_data.items():
        text = data["text"]
        paragraphs = text.split("\n\n")

        prev_topic = None
        prev_score = 0

        for para in paragraphs:
            para_lower = para.lower()
            para_cites = [c for c in get_citations(para)
                          if isinstance(c, FullCaseCitation)]

            # Score paragraph against each doctrinal topic
            best_topic = None
            best_score = 0
            for topic, keywords in TOPIC_KEYWORDS.items():
                s = score_topic(para_lower, keywords)
                if s > best_score:
                    best_score = s
                    best_topic = topic

            # Direct match: paragraph strongly matches a topic
            if best_score >= 2:
                prev_topic = best_topic
                prev_score = best_score
            # Contextual inheritance: paragraph weakly matches and the
            # previous paragraph had a strong match -- continue the thread
            elif best_score >= 1 and prev_topic and prev_score >= 2:
                best_topic = prev_topic
            else:
                best_topic = None

            if para_cites and best_topic:
                for cite in para_cites:
                    triple = tuple(extract_full_case_triple(cite))
                    threads[best_topic]["cases"].add(triple)
                    threads[best_topic]["documents"].add(filename)

    # Convert to output format, filtering to threads with >= 2 cases
    result = []
    for name, data in sorted(threads.items()):
        if len(data["cases"]) >= 2:
            cases = sorted(
                data["cases"],
                key=lambda x: int(x[0]) if x[0].isdigit() else 0,
            )
            result.append({
                "thread_name": name,
                "cases": [list(c) for c in cases],
                "documents": sorted(data["documents"]),
            })

    return result


# ---------------------------------------------------------------------------
# Abrogation / vacatur detection
# ---------------------------------------------------------------------------
def detect_abrogations(filename, text, all_citations):
    """Detect cases explicitly stated as abrogated or vacated in the text."""
    risks = []
    full_cites = [c for c in all_citations if isinstance(c, FullCaseCitation)]

    # ---- Pattern 1: "[CaseName] abrogated ... [Citation]" ----
    for m in re.finditer(r"(\w+)\s+(?:effectively\s+)?abrogat\w*\b", text, re.IGNORECASE):
        case_name = m.group(1).lower()

        # The citation immediately after "abrogated" is the abrogated case
        after = text[m.end(): m.end() + 500]
        after_cites = [c for c in get_citations(after)
                       if isinstance(c, FullCaseCitation)]
        if not after_cites:
            continue
        abrogated = extract_full_case_triple(after_cites[0])

        # Find the abrogating case by searching for the case name near
        # a full citation earlier in the document
        abrogating = None
        for sm in re.finditer(re.escape(case_name), text, re.IGNORECASE):
            context = text[sm.start(): sm.start() + 200]
            context_cites = [c for c in get_citations(context)
                             if isinstance(c, FullCaseCitation)]
            for cc in context_cites:
                candidate = extract_full_case_triple(cc)
                if candidate != abrogated:
                    abrogating = candidate
                    break
            if abrogating:
                break

        if abrogating:
            risks.append({
                "abrogated_case": abrogated,
                "abrogating_case": abrogating,
                "document": filename,
                "reason": "Explicitly stated as abrogated in opinion text",
            })

    # ---- Pattern 2: "vacated [both] [decisions] in [Citation]" ----
    for m in re.finditer(
        r"vacat\w+\s+(?:both\s+)?(?:those\s+)?(?:decisions?\s+)?in\s+",
        text, re.IGNORECASE,
    ):
        after = text[m.end(): m.end() + 300]
        after_cites = [c for c in get_citations(after)
                       if isinstance(c, FullCaseCitation)]
        if not after_cites:
            continue
        vacating = extract_full_case_triple(after_cites[0])

        # Determine how many prior decisions were vacated
        match_text = text[max(0, m.start() - 5): m.end()]
        num_vacated = 2 if "both" in match_text.lower() else 1

        # Look backward for the vacated cases
        before = text[max(0, m.start() - 500): m.start()]
        before_cites = [c for c in get_citations(before)
                        if isinstance(c, FullCaseCitation)]
        for bc in before_cites[-num_vacated:]:
            vacated = extract_full_case_triple(bc)
            if vacated != vacating:
                risks.append({
                    "abrogated_case": vacated,
                    "abrogating_case": vacating,
                    "document": filename,
                    "reason": "Explicitly vacated as stated in opinion text",
                })

    return risks


# ---------------------------------------------------------------------------
# Per-document processing
# ---------------------------------------------------------------------------
def process_document(filename, text):
    """Process a single opinion document and return all analysis results."""
    court_id = identify_court(text)
    citations = get_citations(text)
    resolved = resolve_citations(citations)

    # ---- Citation extraction ----
    full_case_cites = []
    id_count = 0
    supra_count = 0

    for cite in citations:
        if isinstance(cite, FullCaseCitation):
            triple = extract_full_case_triple(cite)
            full_case_cites.append(triple)
        elif isinstance(cite, IdCitation):
            id_count += 1
        elif isinstance(cite, SupraCitation):
            supra_count += 1

    full_case_cites.sort(key=lambda x: int(x[0]) if x[0].isdigit() else 0)

    # ---- Id. resolution ----
    id_resolutions = []
    orphan_ids = []

    for resource, cite_list in resolved.items():
        full_in_res = [c for c in cite_list if isinstance(c, FullCaseCitation)]
        id_in_res = [c for c in cite_list if isinstance(c, IdCitation)]

        if full_in_res and id_in_res:
            antecedent = full_in_res[0]
            antecedent_triple = extract_full_case_triple(antecedent)
            for ic in id_in_res:
                pin = ""
                if hasattr(ic, "metadata") and ic.metadata:
                    pin = getattr(ic.metadata, "pin_cite", "") or ""
                id_resolutions.append({
                    "id_pin": pin,
                    "resolves_to": antecedent_triple,
                })
        elif id_in_res and not full_in_res:
            for ic in id_in_res:
                orphan_ids.append({
                    "file": filename,
                    "text": str(ic),
                })

    # ---- Authority hierarchy ----
    authority = []
    for cite in citations:
        if isinstance(cite, FullCaseCitation):
            triple = extract_full_case_triple(cite)
            cited_court = get_cited_court(cite)
            reporter = cite.groups.get("reporter", "")
            binding = is_binding_authority(court_id, cited_court, reporter)
            authority.append({
                "citation": triple,
                "cited_court": cited_court,
                "binding": binding,
            })
    authority.sort(
        key=lambda x: int(x["citation"][0]) if x["citation"][0].isdigit() else 0
    )

    # ---- Court-reporter mismatches ----
    mismatches = []
    for cite in citations:
        if not isinstance(cite, FullCaseCitation):
            continue
        reporter = cite.groups.get("reporter", "")
        court_from_meta = ""
        if hasattr(cite, "metadata") and cite.metadata:
            court_from_meta = getattr(cite.metadata, "court", "") or ""
        if reporter in SCOTUS_REPORTERS and court_from_meta and court_from_meta not in ("", "scotus"):
            mismatches.append({
                "file": filename,
                "citation": extract_full_case_triple(cite),
                "expected_court_type": (
                    f"Reporter '{reporter}' implies SCOTUS but parenthetical "
                    f"attributes to '{court_from_meta}'"
                ),
            })

    return {
        "court_id": court_id,
        "full_case": full_case_cites,
        "id_citations": id_count,
        "supra_citations": supra_count,
        "id_resolutions": id_resolutions,
        "orphan_ids": orphan_ids,
        "authority": authority,
        "mismatches": mismatches,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    report = {
        "court_mapping": {},
        "citations_per_document": {},
        "id_resolutions": {},
        "scotus_shared": [],
        "reporter_frequency": {},
        "authority_hierarchy": {},
        "doctrinal_threads": [],
        "anomalies": {
            "orphan_id_citations": [],
            "court_reporter_mismatches": [],
            "abrogation_risks": [],
        },
    }

    scotus_index = defaultdict(set)
    reporter_counts = defaultdict(int)
    doc_data = {}

    files = sorted(f for f in os.listdir(CORPUS_DIR) if f.endswith(".txt"))

    for filename in files:
        filepath = os.path.join(CORPUS_DIR, filename)
        with open(filepath) as f:
            text = f.read()

        result = process_document(filename, text)

        report["court_mapping"][filename] = result["court_id"]
        report["citations_per_document"][filename] = {
            "full_case": result["full_case"],
            "id_citations": result["id_citations"],
            "supra_citations": result["supra_citations"],
        }
        report["id_resolutions"][filename] = result["id_resolutions"]
        report["authority_hierarchy"][filename] = result["authority"]

        report["anomalies"]["orphan_id_citations"].extend(result["orphan_ids"])
        report["anomalies"]["court_reporter_mismatches"].extend(result["mismatches"])

        # Abrogation detection
        all_cites = get_citations(text)
        abrog = detect_abrogations(filename, text, all_cites)
        report["anomalies"]["abrogation_risks"].extend(abrog)

        # Build cross-document indices
        for triple in result["full_case"]:
            vol, rep, pg = triple
            if rep == "U.S.":
                scotus_index[(vol, pg)].add(filename)
            reporter_counts[rep] += 1

        doc_data[filename] = {"text": text}

    # ---- Cross-document SCOTUS shared citations ----
    scotus_shared = []
    for (vol, pg), docs in sorted(
        scotus_index.items(),
        key=lambda x: int(x[0][0]) if x[0][0].isdigit() else 0,
    ):
        if len(docs) > 1:
            scotus_shared.append({
                "citation": [vol, "U.S.", pg],
                "documents": sorted(docs),
            })
    report["scotus_shared"] = scotus_shared

    # ---- Reporter frequency ----
    report["reporter_frequency"] = dict(sorted(reporter_counts.items()))

    # ---- Doctrinal threads ----
    report["doctrinal_threads"] = identify_doctrinal_threads(doc_data)

    # ---- Write output ----
    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {OUTPUT_PATH}")
    print(f"Processed {len(files)} documents")
    print(f"Court mappings: {report['court_mapping']}")
    print(f"SCOTUS shared citations: {len(report['scotus_shared'])}")
    print(f"Reporter frequency: {report['reporter_frequency']}")
    print(f"Authority hierarchy entries: {sum(len(v) for v in report['authority_hierarchy'].values())}")
    print(f"Doctrinal threads: {len(report['doctrinal_threads'])}")
    print(f"Abrogation risks: {len(report['anomalies']['abrogation_risks'])}")


if __name__ == "__main__":
    main()
