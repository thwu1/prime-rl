#!/usr/bin/env python3

"""
Clinical NLP Pipeline: Multi-format entity extraction with section-aware
assertion detection, FTS5-based term lookup, and FHIR output generation.
"""

import json
import re
import os
import csv
import sqlite3
import subprocess
import glob as glob_mod


# ---------------------------------------------------------------------------
# String similarity
# ---------------------------------------------------------------------------

def levenshtein_distance(s1, s2):
    """Classic DP Levenshtein edit distance."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(
                prev[j + 1] + 1,
                curr[j] + 1,
                prev[j] + (c1 != c2),
            ))
        prev = curr
    return prev[-1]


def normalized_similarity(a, b):
    """Normalised Levenshtein similarity in [0, 1]."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    d = levenshtein_distance(a.lower(), b.lower())
    return 1.0 - d / max(len(a), len(b))


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

def tokenize(text):
    """Return list of {text, start, end} dicts, preserving hyphens/slashes."""
    return [
        {"text": m.group(), "start": m.start(), "end": m.end()}
        for m in re.finditer(r"[\w]+(?:[/'-][\w]+)*", text)
    ]


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------

def split_sentences(text):
    """Split on '. ' followed by an uppercase letter."""
    boundaries = [0]
    for m in re.finditer(r"\.\s+(?=[A-Z])", text):
        boundaries.append(m.end())
    sents = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(text)
        s = text[start:end].rstrip()
        if s:
            sents.append({"text": s, "start": start})
    return sents


# ---------------------------------------------------------------------------
# CDA XML parsing via xmlstarlet
# ---------------------------------------------------------------------------

def parse_cda_xml(xml_path):
    """Parse an HL7 CDA XML document using xmlstarlet."""
    # Extract note_id from id/@extension
    result = subprocess.run(
        ["xmlstarlet", "sel", "-N", "hl7=urn:hl7-org:v3",
         "-t", "-v", "//hl7:ClinicalDocument/hl7:id/@extension", xml_path],
        capture_output=True, text=True
    )
    note_id = result.stdout.strip()

    # Extract sections: code|||displayName|||text
    result = subprocess.run(
        ["xmlstarlet", "sel", "-N", "hl7=urn:hl7-org:v3",
         "-t", "-m", "//hl7:section",
         "-v", "hl7:code/@code", "-o", "|||",
         "-v", "hl7:code/@displayName", "-o", "|||",
         "-v", "normalize-space(hl7:text)", "-n", xml_path],
        capture_output=True, text=True
    )

    sections = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|||")
        if len(parts) == 3:
            sections.append({
                "code": parts[0].strip(),
                "display_name": parts[1].strip(),
                "text": parts[2].strip()
            })

    return note_id, sections


# ---------------------------------------------------------------------------
# Section-aware processing
# ---------------------------------------------------------------------------

# LOINC codes -> assertion defaults (clinical domain knowledge)
# 11348-0 = Past Medical History -> historical context
# 10157-6 = Family History -> exclude (describes relatives, not patient)
SECTION_DEFAULTS = {
    "11348-0": "historical",
    "10157-6": "exclude",
}


def get_section_default(section_code):
    return SECTION_DEFAULTS.get(section_code, "affirmed")


# ---------------------------------------------------------------------------
# FTS5-based lexicon
# ---------------------------------------------------------------------------

MIN_FUZZY_LEN = 5
SIMILARITY_THRESHOLD = 0.85


class LexiconFTS:
    """Medical terminology lexicon backed by SQLite FTS5."""

    def __init__(self, db_path):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.entries_by_tid = {}
        self.entries = []
        self.max_tok = 0
        self._load_all()

    def _load_all(self):
        c = self.conn.cursor()
        c.execute("""
            SELECT form, CAST(term_id AS INTEGER) as tid, canonical,
                   entity_type, code, code_system_name
            FROM terms_fts
        """)
        for row in c:
            tid = row["tid"]
            if tid not in self.entries_by_tid:
                self.entries_by_tid[tid] = {
                    "canonical": row["canonical"],
                    "type": row["entity_type"],
                    "code": row["code"],
                    "code_system": row["code_system_name"],
                    "forms": [],
                    "form_tc": {},
                }
            self.entries_by_tid[tid]["forms"].append(row["form"])

        for entry in self.entries_by_tid.values():
            for f in entry["forms"]:
                tc = len(tokenize(f))
                entry["form_tc"][f] = tc
                self.max_tok = max(self.max_tok, tc)
            self.entries.append(entry)

    def fts5_search(self, query_tokens):
        """Use FTS5 MATCH to find candidate term IDs."""
        terms = [t for t in query_tokens if len(t) > 1]
        if not terms:
            return set()
        fts_query = " OR ".join(f'"{t}"' for t in terms)
        try:
            c = self.conn.cursor()
            c.execute(
                "SELECT DISTINCT CAST(term_id AS INTEGER) as tid "
                "FROM terms_fts WHERE terms_fts MATCH ?",
                (fts_query,)
            )
            return {row["tid"] for row in c}
        except Exception:
            return set()

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# Entity extraction (FTS5 candidate retrieval + edit distance)
# ---------------------------------------------------------------------------

def extract_entities(tokens, sent_text, lexicon):
    entities = []
    i = 0
    while i < len(tokens):
        best = None
        best_span = 0
        best_sim = 0.0

        for span_len in range(min(lexicon.max_tok, len(tokens) - i), 0, -1):
            span_toks = tokens[i:i + span_len]
            span_text = sent_text[span_toks[0]["start"]:span_toks[-1]["end"]]
            span_lower = span_text.lower()

            # FTS5 candidate retrieval
            query_tokens = [t["text"].lower() for t in span_toks]
            candidate_tids = lexicon.fts5_search(query_tokens)
            candidates = [lexicon.entries_by_tid[tid]
                          for tid in candidate_tids
                          if tid in lexicon.entries_by_tid]

            # Fall back to all entries for fuzzy matching if no FTS5 hits
            if not candidates:
                candidates = lexicon.entries

            for entry in candidates:
                for form in entry["forms"]:
                    form_lower = form.lower()

                    if span_lower == form_lower:
                        sim = 1.0
                    elif (len(span_text) >= MIN_FUZZY_LEN
                          and len(form) >= MIN_FUZZY_LEN):
                        if entry["form_tc"][form] != span_len:
                            continue
                        sim = normalized_similarity(span_text, form)
                    else:
                        continue

                    if sim >= SIMILARITY_THRESHOLD and (
                        span_len > best_span
                        or (span_len == best_span and sim > best_sim)
                    ):
                        best = {
                            "text": span_text,
                            "start": span_toks[0]["start"],
                            "end": span_toks[-1]["end"],
                            "type": entry["type"],
                            "resolved_code": entry["code"],
                            "resolved_term": entry["canonical"],
                            "similarity": round(sim, 4),
                            "tok_s": i,
                            "tok_e": i + span_len - 1,
                        }
                        best_span = span_len
                        best_sim = sim

            if best and best_span == span_len:
                break

        if best:
            entities.append(best)
            i += best_span
        else:
            i += 1

    return entities


# ---------------------------------------------------------------------------
# Trigger detection
# ---------------------------------------------------------------------------

def detect_triggers(tokens, trigger_cfg):
    """Return (active_triggers, termination_positions)."""
    pseudo_pos = set()
    for phrase in trigger_cfg.get("pseudo_negation", []):
        ptoks = [t["text"].lower() for t in tokenize(phrase)]
        plen = len(ptoks)
        for i in range(len(tokens) - plen + 1):
            if all(tokens[i + j]["text"].lower() == ptoks[j] for j in range(plen)):
                pseudo_pos.update(range(i, i + plen))

    trig_defs = []
    for cat in ("pre_negation", "post_negation", "hypothetical", "historical"):
        for phrase in trigger_cfg.get(cat, []):
            ptoks = [t["text"].lower() for t in tokenize(phrase)]
            trig_defs.append({"cat": cat, "toks": ptoks, "len": len(ptoks)})
    trig_defs.sort(key=lambda x: x["len"], reverse=True)

    found = []
    used = set()
    for i in range(len(tokens)):
        if i in used:
            continue
        for td in trig_defs:
            tl = td["len"]
            if i + tl > len(tokens):
                continue
            positions = range(i, i + tl)
            if any(p in used or p in pseudo_pos for p in positions):
                continue
            if all(tokens[i + j]["text"].lower() == td["toks"][j] for j in range(tl)):
                found.append({"cat": td["cat"], "start": i, "end": i + tl - 1})
                used.update(positions)
                break

    term_defs = []
    for phrase in trigger_cfg.get("termination", []):
        ptoks = [t["text"].lower() for t in tokenize(phrase)]
        term_defs.append({"toks": ptoks, "len": len(ptoks)})
    term_defs.sort(key=lambda x: x["len"], reverse=True)

    term_pos = []
    for i in range(len(tokens)):
        for td in term_defs:
            tl = td["len"]
            if i + tl > len(tokens):
                continue
            if all(tokens[i + j]["text"].lower() == td["toks"][j] for j in range(tl)):
                term_pos.append(i)
                break

    return found, term_pos


# ---------------------------------------------------------------------------
# Assertion determination (with section default support)
# ---------------------------------------------------------------------------

def determine_assertion(ent_tok_s, ent_tok_e, triggers, term_pos, scope_window,
                        section_default="affirmed"):
    best_trig = None
    best_dist = float("inf")

    for trig in triggers:
        cat = trig["cat"]
        ts, te = trig["start"], trig["end"]

        if cat in ("pre_negation", "hypothetical", "historical"):
            if ent_tok_s > te:
                dist = ent_tok_s - te
                if dist <= scope_window:
                    if any(te < tp < ent_tok_s for tp in term_pos):
                        continue
                    if dist < best_dist:
                        best_dist = dist
                        best_trig = trig

        elif cat == "post_negation":
            if ent_tok_e < ts:
                dist = ts - ent_tok_e
                if dist <= scope_window:
                    if any(ent_tok_e < tp < ts for tp in term_pos):
                        continue
                    if dist < best_dist:
                        best_dist = dist
                        best_trig = trig

    if best_trig is None:
        # No explicit trigger found -> use section default
        return section_default

    c = best_trig["cat"]
    if c in ("pre_negation", "post_negation"):
        return "negated"
    return c


# ---------------------------------------------------------------------------
# Note processing
# ---------------------------------------------------------------------------

def process_json_note(note, lexicon, trigger_cfg):
    """Process a JSON-format note (no section awareness)."""
    text = note["text"]
    scope_window = trigger_cfg.get("scope_window", 6)
    sentences = split_sentences(text)

    all_ents = []
    for sent in sentences:
        s_text = sent["text"]
        s_off = sent["start"]

        tokens = tokenize(s_text)
        if not tokens:
            continue

        ents = extract_entities(tokens, s_text, lexicon)
        trigs, terms = detect_triggers(tokens, trigger_cfg)

        for e in ents:
            e["assertion"] = determine_assertion(
                e["tok_s"], e["tok_e"], trigs, terms, scope_window
            )
            e["start"] += s_off
            e["end"] += s_off

        all_ents.extend(ents)

    return {
        "note_id": note["note_id"],
        "entities": [
            {k: e[k] for k in ("text", "start", "end", "type", "assertion",
                                "resolved_code", "resolved_term", "similarity")}
            for e in all_ents
        ],
    }


def process_cda_note(note_id, sections, lexicon, trigger_cfg):
    """Process a CDA-format note with section awareness."""
    scope_window = trigger_cfg.get("scope_window", 6)

    # Reconstruct full text by joining all section texts with newline
    section_texts = [s["text"] for s in sections]
    full_text = "\n".join(section_texts)

    all_ents = []
    current_offset = 0

    for section in sections:
        section_code = section["code"]
        section_default = get_section_default(section_code)

        # Skip excluded sections (Family History - describes relatives)
        if section_default == "exclude":
            current_offset += len(section["text"]) + 1
            continue

        s_text = section["text"]
        sentences = split_sentences(s_text)

        for sent in sentences:
            sent_text = sent["text"]
            sent_off = sent["start"]

            tokens = tokenize(sent_text)
            if not tokens:
                continue

            ents = extract_entities(tokens, sent_text, lexicon)
            trigs, terms = detect_triggers(tokens, trigger_cfg)

            for e in ents:
                e["assertion"] = determine_assertion(
                    e["tok_s"], e["tok_e"], trigs, terms, scope_window,
                    section_default=section_default
                )
                e["start"] += sent_off + current_offset
                e["end"] += sent_off + current_offset

            all_ents.extend(ents)

        current_offset += len(s_text) + 1

    return {
        "note_id": note_id,
        "entities": [
            {k: e[k] for k in ("text", "start", "end", "type", "assertion",
                                "resolved_code", "resolved_term", "similarity")}
            for e in all_ents
        ],
    }, full_text


# ---------------------------------------------------------------------------
# FHIR output generation via jq
# ---------------------------------------------------------------------------

JQ_FILTER = r"""
def assertion_to_clinical_status:
  if . == "historical" then "resolved"
  else "active"
  end;

def assertion_to_verification_status:
  if . == "affirmed" or . == "historical" then "confirmed"
  elif . == "negated" then "refuted"
  elif . == "hypothetical" then "provisional"
  else "unconfirmed"
  end;

{
  resourceType: "Bundle",
  type: "collection",
  entry: [
    .[] | .note_id as $nid |
    .entities[] |
    select(.type == "CONDITION" or .type == "SYMPTOM") |
    {
      resource: {
        resourceType: "Condition",
        id: ($nid + "-" + (.start | tostring)),
        clinicalStatus: {
          coding: [{
            system: "http://terminology.hl7.org/CodeSystem/condition-clinical",
            code: (.assertion | assertion_to_clinical_status)
          }]
        },
        verificationStatus: {
          coding: [{
            system: "http://terminology.hl7.org/CodeSystem/condition-ver-status",
            code: (.assertion | assertion_to_verification_status)
          }]
        },
        code: {
          coding: [{
            system: "http://hl7.org/fhir/sid/icd-10-cm",
            code: .resolved_code,
            display: .resolved_term
          }],
          text: .text
        },
        subject: { reference: "Patient/unknown" },
        note: [{ text: ("Source note: " + $nid) }]
      }
    }
  ]
}
"""


def generate_fhir_output():
    """Write jq filter and run it to produce FHIR Bundle."""
    jq_path = "/app/fhir_transform.jq"
    with open(jq_path, "w") as f:
        f.write(JQ_FILTER)

    result = subprocess.run(
        ["jq", "-f", jq_path, "/app/output/results.json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"jq failed: {result.stderr}")

    with open("/app/output/fhir_conditions.json", "w") as f:
        f.write(result.stdout)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Load JSON notes
    with open("/app/data/clinical_notes.json") as f:
        json_notes = json.load(f)

    with open("/app/data/assertion_rules.json") as f:
        trigger_cfg = json.load(f)

    # Initialize FTS5-backed lexicon
    lexicon = LexiconFTS("/app/data/lexicon.db")

    results = []
    note_texts = {}

    # Process JSON notes (no section awareness)
    for note in json_notes:
        result = process_json_note(note, lexicon, trigger_cfg)
        results.append(result)
        note_texts[note["note_id"]] = note["text"]

    # Parse and process CDA XML notes (section-aware)
    cda_dir = "/app/data/notes_cda"
    xml_files = sorted(glob_mod.glob(os.path.join(cda_dir, "*.xml")))

    for xml_path in xml_files:
        note_id, sections = parse_cda_xml(xml_path)
        result, full_text = process_cda_note(
            note_id, sections, lexicon, trigger_cfg
        )
        results.append(result)
        note_texts[note_id] = full_text

    lexicon.close()

    # Sort results by note_id
    results.sort(key=lambda x: x["note_id"])

    os.makedirs("/app/output", exist_ok=True)

    # Write JSON results
    with open("/app/output/results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Write note texts mapping
    with open("/app/output/note_texts.json", "w") as f:
        json.dump(note_texts, f, indent=2)

    # Write summary CSV
    with open("/app/output/summary.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["note_id", "affirmed", "negated", "hypothetical", "historical"])
        for note_result in results:
            counts = {"affirmed": 0, "negated": 0, "hypothetical": 0, "historical": 0}
            for ent in note_result["entities"]:
                counts[ent["assertion"]] += 1
            writer.writerow([
                note_result["note_id"],
                counts["affirmed"],
                counts["negated"],
                counts["hypothetical"],
                counts["historical"],
            ])

    # Generate FHIR Bundle via jq
    generate_fhir_output()

    print(f"Processed {len(results)} notes -> /app/output/")


if __name__ == "__main__":
    main()
