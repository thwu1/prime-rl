#!/usr/bin/env python3
"""Generate NIST CDF election test data with planted cross-format violations.

Creates three interrelated election data files following NIST SP 1500-series:
  - bd.json  (Ballot Definition, SP 1500-20 v1)
  - cvr.json (Cast Vote Records, SP 1500-103 v1)
  - err.json (Election Results Reporting, SP 1500-100 v2)

Seven cross-format referential integrity violations are planted.
"""
import json
import os
from collections import defaultdict

OUTDIR = "/app/data"

# ── Selection-ID shorthand maps ──────────────────────────────────────────────
SEL = {
    "pres":   {"dem": "cs-pres-dem", "rep": "cs-pres-rep", "lib": "cs-pres-lib", "wi": "cs-pres-wi"},
    "sen":    {"dem": "cs-sen-dem", "rep": "cs-sen-rep", "wi": "cs-sen-wi"},
    "cong":   {"dem": "cs-cong1-dem", "rep": "cs-cong1-rep"},
    "assess": {"1": "cs-assess-1", "2": "cs-assess-2", "3": "cs-assess-3"},
    "prop":   {"yes": "cs-prop1-yes", "no": "cs-prop1-no"},
}

# ── Vote patterns per precinct (compact tuples) ─────────────────────────────
# Precinct 1 (bs-1): pres, sen, cong, (a1,a2), prop
P1 = [
    ("dem","dem","dem",("1","2"),"yes"), ("dem","dem","dem",("1","3"),"yes"),
    ("rep","rep","rep",("2","3"),"no"),  ("rep","rep","rep",("1","2"),"no"),
    ("dem","dem","dem",("1","2"),"yes"), ("lib","dem","dem",("2","3"),"yes"),
    ("rep","rep","rep",("1","3"),"no"),  ("dem","dem","dem",("1","2"),"yes"),
    ("wi","wi","rep",("2","3"),"no"),    ("lib","rep","dem",("1","3"),"yes"),
]
# Precinct 2 (bs-2): pres, sen, (a1,a2), prop  [no congress]
P2 = [
    ("dem","dem",("1","2"),"yes"), ("rep","rep",("2","3"),"no"),
    ("dem","dem",("1","3"),"yes"), ("rep","rep",("1","2"),"no"),
    ("dem","dem",("1","2"),"yes"), ("lib","rep",("2","3"),"no"),
    ("dem","dem",("1","3"),"yes"), ("rep","rep",("1","2"),"no"),
    ("wi","dem",("2","3"),"yes"),  ("dem","dem",("1","3"),"yes"),
]
# Precinct 3 (bs-3): pres, cong, (a1,a2), prop  [no senate]
P3 = [
    ("dem","dem",("1","2"),"yes"), ("rep","rep",("2","3"),"no"),
    ("dem","dem",("1","3"),"yes"), ("rep","rep",("1","2"),"no"),
    ("lib","dem",("1","2"),"yes"), ("dem","dem",("2","3"),"yes"),
    ("wi","rep",("1","3"),"no"),   ("rep","rep",("1","2"),"no"),
    ("lib","dem",("2","3"),"yes"), ("dem","dem",("1","3"),"yes"),
]


def expand_p1(t):
    p, s, c, (a1, a2), pr = t
    return [("cc-president",[SEL["pres"][p]]),("cc-senate",[SEL["sen"][s]]),
            ("cc-congress-1",[SEL["cong"][c]]),("cc-county-assessor",[SEL["assess"][a1],SEL["assess"][a2]]),
            ("bm-proposal-1",[SEL["prop"][pr]])]

def expand_p2(t):
    p, s, (a1, a2), pr = t
    return [("cc-president",[SEL["pres"][p]]),("cc-senate",[SEL["sen"][s]]),
            ("cc-county-assessor",[SEL["assess"][a1],SEL["assess"][a2]]),
            ("bm-proposal-1",[SEL["prop"][pr]])]

def expand_p3(t):
    p, c, (a1, a2), pr = t
    return [("cc-president",[SEL["pres"][p]]),("cc-congress-1",[SEL["cong"][c]]),
            ("cc-county-assessor",[SEL["assess"][a1],SEL["assess"][a2]]),
            ("bm-proposal-1",[SEL["prop"][pr]])]


def make_cvr_record(num, bs_id, gpu_id, votes):
    """Build one CVR record.  votes = [(contest_id, [sel_ids]), ...]"""
    snap_id = f"snapshot-{num:03d}"
    contests = []
    for cid, sels in votes:
        cs = []
        for sid in sels:
            cs.append({"@type":"CVR.CVRContestSelection",
                        "ContestSelectionId": sid,
                        "SelectionPosition":[{"HasIndication":"yes","IsAllocable":"yes","NumberVotes":1}]})
        contests.append({"@type":"CVR.CVRContest","ContestId":cid,"CVRContestSelection":cs})
    return {
        "@type":"CVR.CVR",
        "BallotStyleId": bs_id,
        "BallotStyleUnitId": gpu_id,
        "CreatingDeviceId":"scanner-01",
        "CurrentSnapshotId": snap_id,
        "ElectionId":"election-gen-test-01",
        "UniqueId": f"ballot-{num:03d}",
        "CVRSnapshot":[{
            "@id": snap_id, "@type":"CVR.CVRSnapshot","Type":"original",
            "CVRContest": contests
        }]
    }


def build_bd():
    """Construct the Ballot Definition JSON."""
    def csel(sid, cands):
        return {"@id":sid,"@type":"BallotDefinition.CandidateSelection","CandidateIds":cands}
    def wsel(sid):
        return {"@id":sid,"@type":"BallotDefinition.CandidateSelection","IsWriteIn":True}
    def bmsel(sid, text):
        return {"@id":sid,"@type":"BallotDefinition.BallotMeasureSelection",
                "Selection":{"Text":[{"Content":text,"Language":"en"}]}}
    def oc(cid):
        return {"@type":"BallotDefinition.OrderedContest","ContestId":cid}

    return {"BallotDefinition.BallotDefinition":{
        "Election":[{
            "@id":"election-gen-test-01",
            "@type":"BallotDefinition.Election",
            "Name":{"Text":[{"Content":"General Election Test 01","Language":"en"}]},
            "StartDate":"2024-11-05","EndDate":"2024-11-05","Type":"general",
            "ElectionScopeId":"gpu-county",
            "Contest":[
                {"@id":"cc-president","@type":"BallotDefinition.CandidateContest",
                 "Name":"President of the United States","VotesAllowed":1,
                 "ContestSelection":[csel("cs-pres-dem",["cand-01"]),csel("cs-pres-rep",["cand-02"]),
                                     csel("cs-pres-lib",["cand-03"]),wsel("cs-pres-wi")]},
                {"@id":"cc-senate","@type":"BallotDefinition.CandidateContest",
                 "Name":"United States Senate","VotesAllowed":1,
                 "ContestSelection":[csel("cs-sen-dem",["cand-05"]),csel("cs-sen-rep",["cand-06"]),
                                     wsel("cs-sen-wi")]},
                {"@id":"cc-congress-1","@type":"BallotDefinition.CandidateContest",
                 "Name":"US Congress District 1","VotesAllowed":1,
                 "ContestSelection":[csel("cs-cong1-dem",["cand-08"]),csel("cs-cong1-rep",["cand-09"])]},
                {"@id":"cc-county-assessor","@type":"BallotDefinition.CandidateContest",
                 "Name":"County Assessor","VotesAllowed":2,
                 "ContestSelection":[csel("cs-assess-1",["cand-10"]),csel("cs-assess-2",["cand-11"]),
                                     csel("cs-assess-3",["cand-12"])]},
                {"@id":"bm-proposal-1","@type":"BallotDefinition.BallotMeasureContest",
                 "Name":"Proposal 1 - School Bond","VotesAllowed":1,
                 "ContestSelection":[bmsel("cs-prop1-yes","Yes"),bmsel("cs-prop1-no","No")]},
            ],
            "BallotStyle":[
                {"@id":"bs-1","@type":"BallotDefinition.BallotStyle","GpUnitIds":["gpu-precinct-1"],
                 "OrderedContent":[oc("cc-president"),oc("cc-senate"),oc("cc-congress-1"),
                                   oc("cc-county-assessor"),oc("bm-proposal-1")]},
                {"@id":"bs-2","@type":"BallotDefinition.BallotStyle","GpUnitIds":["gpu-precinct-2"],
                 "OrderedContent":[oc("cc-president"),oc("cc-senate"),
                                   oc("cc-county-assessor"),oc("bm-proposal-1")]},
                {"@id":"bs-3","@type":"BallotDefinition.BallotStyle","GpUnitIds":["gpu-precinct-3"],
                 "OrderedContent":[oc("cc-president"),oc("cc-congress-1"),
                                   oc("cc-county-assessor"),oc("bm-proposal-1")]},
            ],
        }],
        "GpUnit":[
            {"@id":"gpu-county","@type":"BallotDefinition.ReportingUnit",
             "Name":{"Text":[{"Content":"Test County","Language":"en"}]},"Type":"county"},
            {"@id":"gpu-precinct-1","@type":"BallotDefinition.ReportingUnit",
             "Name":{"Text":[{"Content":"Precinct 1","Language":"en"}]},"Type":"precinct"},
            {"@id":"gpu-precinct-2","@type":"BallotDefinition.ReportingUnit",
             "Name":{"Text":[{"Content":"Precinct 2","Language":"en"}]},"Type":"precinct"},
            {"@id":"gpu-precinct-3","@type":"BallotDefinition.ReportingUnit",
             "Name":{"Text":[{"Content":"Precinct 3","Language":"en"}]},"Type":"precinct"},
        ],
        "Party":[
            {"@id":"party-dem","@type":"BallotDefinition.Party",
             "Name":{"Text":[{"Content":"Democratic Party","Language":"en"}]},
             "Abbreviation":{"Text":[{"Content":"DEM","Language":"en"}]}},
            {"@id":"party-rep","@type":"BallotDefinition.Party",
             "Name":{"Text":[{"Content":"Republican Party","Language":"en"}]},
             "Abbreviation":{"Text":[{"Content":"REP","Language":"en"}]}},
            {"@id":"party-lib","@type":"BallotDefinition.Party",
             "Name":{"Text":[{"Content":"Libertarian Party","Language":"en"}]},
             "Abbreviation":{"Text":[{"Content":"LIB","Language":"en"}]}},
        ],
        "Candidate":[
            {"@id":"cand-01","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"Alice Smith","Language":"en"}]},"PartyId":"party-dem"},
            {"@id":"cand-02","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"Bob Jones","Language":"en"}]},"PartyId":"party-rep"},
            {"@id":"cand-03","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"Carol White","Language":"en"}]},"PartyId":"party-lib"},
            {"@id":"cand-05","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"David Brown","Language":"en"}]},"PartyId":"party-dem"},
            {"@id":"cand-06","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"Eve Davis","Language":"en"}]},"PartyId":"party-rep"},
            {"@id":"cand-08","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"Frank Wilson","Language":"en"}]},"PartyId":"party-dem"},
            {"@id":"cand-09","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"Grace Lee","Language":"en"}]},"PartyId":"party-rep"},
            {"@id":"cand-10","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"Henry Adams","Language":"en"}]},"PartyId":"party-dem"},
            {"@id":"cand-11","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"Irene Clark","Language":"en"}]},"PartyId":"party-rep"},
            {"@id":"cand-12","@type":"BallotDefinition.Candidate",
             "BallotName":{"Text":[{"Content":"Jack Turner","Language":"en"}]}},
        ],
    }}


def build_cvr_and_tallies():
    """Build CVR records (valid + violated) and compute correct tallies."""
    tallies = defaultdict(lambda: defaultdict(int))
    records = []
    num = 0

    def add_ballot(bs, gpu, votes):
        nonlocal num
        num += 1
        records.append(make_cvr_record(num, bs, gpu, votes))
        for cid, sels in votes:
            for sid in sels:
                tallies[cid][sid] += 1

    # ── Precinct 1 ──
    for pat in P1:
        add_ballot("bs-1", "gpu-precinct-1", expand_p1(pat))
    # ── Precinct 2 ──
    for pat in P2:
        add_ballot("bs-2", "gpu-precinct-2", expand_p2(pat))
    # ── Precinct 3 ──
    for pat in P3:
        add_ballot("bs-3", "gpu-precinct-3", expand_p3(pat))

    # ── Planted CVR violations ──────────────────────────────────────────────
    # VIOLATION 1: undefined contest "cc-treasurer"
    num += 1
    records.append(make_cvr_record(num, "bs-1", "gpu-precinct-1",
                                   [("cc-treasurer", ["cs-treas-1"])]))
    # VIOLATION 2: undefined ContestSelection "cs-99" in valid contest
    num += 1
    records.append(make_cvr_record(num, "bs-1", "gpu-precinct-1",
                                   [("cc-senate", ["cs-99"])]))
    # VIOLATION 3: undefined GpUnit "gpu-precinct-5"
    num += 1
    records.append(make_cvr_record(num, "bs-1", "gpu-precinct-5", []))

    cvr_data = {"CVR.CastVoteRecordReport":{
        "Election":[{"@id":"election-gen-test-01",
                      "Contest":[{"@id":"cc-president","Name":"President of the United States"},
                                 {"@id":"cc-senate","Name":"United States Senate"},
                                 {"@id":"cc-congress-1","Name":"US Congress District 1"},
                                 {"@id":"cc-county-assessor","Name":"County Assessor"},
                                 {"@id":"bm-proposal-1","Name":"Proposal 1 - School Bond"}]}],
        "GpUnit":[{"@id":"gpu-county","Type":"county","Name":"Test County"},
                  {"@id":"gpu-precinct-1","Type":"precinct","Name":"Precinct 1"},
                  {"@id":"gpu-precinct-2","Type":"precinct","Name":"Precinct 2"},
                  {"@id":"gpu-precinct-3","Type":"precinct","Name":"Precinct 3"}],
        "Party":[{"@id":"party-dem","Name":"Democratic Party"},
                 {"@id":"party-rep","Name":"Republican Party"},
                 {"@id":"party-lib","Name":"Libertarian Party"}],
        "ReportingDevice":[{"@id":"scanner-01","Model":"Optical Scanner 3000","Type":"scan-single"}],
        "CVR": records,
    }}
    return cvr_data, dict(tallies)


def build_err(tallies):
    """Build ERR JSON from correct tallies, then plant violations."""

    def csel(sid, cands, count):
        return {"@id":sid,"@type":"ElectionResults.CandidateSelection",
                "CandidateIds":cands,
                "VoteCounts":[{"Count":count,"GpUnitId":"gpu-county","Type":"total"}]}
    def bmsel(sid, sel_text, count):
        return {"@id":sid,"@type":"ElectionResults.BallotMeasureSelection",
                "Selection":{"Text":[{"Content":sel_text,"Language":"en"}]},
                "VoteCounts":[{"Count":count,"GpUnitId":"gpu-county","Type":"total"}]}

    t = tallies  # shorthand

    contests = [
        {"@id":"cc-president","@type":"ElectionResults.CandidateContest",
         "Name":"President of the United States",
         "ContestSelection":[
             # VIOLATION 4: planted mismatch — report 16 instead of correct 13
             csel("cs-pres-dem",["cand-01"], 16),
             csel("cs-pres-rep",["cand-02"], t["cc-president"]["cs-pres-rep"]),
             csel("cs-pres-lib",["cand-03"], t["cc-president"]["cs-pres-lib"]),
             csel("cs-pres-wi",[],           t["cc-president"]["cs-pres-wi"]),
         ]},
        {"@id":"cc-senate","@type":"ElectionResults.CandidateContest",
         "Name":"United States Senate",
         "ContestSelection":[
             csel("cs-sen-dem",["cand-05"], t["cc-senate"]["cs-sen-dem"]),
             csel("cs-sen-rep",["cand-06"], t["cc-senate"]["cs-sen-rep"]),
             csel("cs-sen-wi",[],           t["cc-senate"]["cs-sen-wi"]),
             # VIOLATION 7: undefined candidate "cand-phantom"
             {"@id":"cs-sen-ind","@type":"ElectionResults.CandidateSelection",
              "CandidateIds":["cand-phantom"],
              "VoteCounts":[{"Count":2,"GpUnitId":"gpu-county","Type":"total"}]},
         ]},
        {"@id":"cc-congress-1","@type":"ElectionResults.CandidateContest",
         "Name":"US Congress District 1",
         "ContestSelection":[
             csel("cs-cong1-dem",["cand-08"], t["cc-congress-1"]["cs-cong1-dem"]),
             csel("cs-cong1-rep",["cand-09"], t["cc-congress-1"]["cs-cong1-rep"]),
         ]},
        {"@id":"cc-county-assessor","@type":"ElectionResults.CandidateContest",
         "Name":"County Assessor",
         "ContestSelection":[
             csel("cs-assess-1",["cand-10"], t["cc-county-assessor"]["cs-assess-1"]),
             csel("cs-assess-2",["cand-11"], t["cc-county-assessor"]["cs-assess-2"]),
             csel("cs-assess-3",["cand-12"], t["cc-county-assessor"]["cs-assess-3"]),
         ]},
        {"@id":"bm-proposal-1","@type":"ElectionResults.BallotMeasureContest",
         "Name":"Proposal 1 - School Bond",
         "ContestSelection":[
             bmsel("cs-prop1-yes","Yes", t["bm-proposal-1"]["cs-prop1-yes"]),
             bmsel("cs-prop1-no","No",   t["bm-proposal-1"]["cs-prop1-no"]),
         ]},
        # VIOLATION 6: undefined contest "cc-comptroller"
        {"@id":"cc-comptroller","@type":"ElectionResults.CandidateContest",
         "Name":"County Comptroller",
         "ContestSelection":[
             {"@id":"cs-comp-1","@type":"ElectionResults.CandidateSelection",
              "CandidateIds":["cand-comp-1"],
              "VoteCounts":[{"Count":55,"GpUnitId":"gpu-county","Type":"total"}]},
         ]},
    ]

    return {"ElectionResults.ElectionReport":{
        "Election":[{
            "@id":"election-gen-test-01",
            "@type":"ElectionResults.Election",
            "Name":{"Text":[{"Content":"General Election Test 01","Language":"en"}]},
            "StartDate":"2024-11-05","EndDate":"2024-11-05","Type":"general",
            "ElectionScopeId":"gpu-county",
            "Contest": contests,
        }],
        "GpUnit":[
            {"@id":"gpu-county","@type":"ElectionResults.ReportingUnit",
             "Name":{"Text":[{"Content":"Test County","Language":"en"}]},"Type":"county"},
            {"@id":"gpu-precinct-1","@type":"ElectionResults.ReportingUnit",
             "Name":{"Text":[{"Content":"Precinct 1","Language":"en"}]},"Type":"precinct"},
            {"@id":"gpu-precinct-2","@type":"ElectionResults.ReportingUnit",
             "Name":{"Text":[{"Content":"Precinct 2","Language":"en"}]},"Type":"precinct"},
            {"@id":"gpu-precinct-3","@type":"ElectionResults.ReportingUnit",
             "Name":{"Text":[{"Content":"Precinct 3","Language":"en"}]},"Type":"precinct"},
        ],
        "Party":[
            {"@id":"party-dem","@type":"ElectionResults.Party",
             "Name":{"Text":[{"Content":"Democratic Party","Language":"en"}]}},
            {"@id":"party-rep","@type":"ElectionResults.Party",
             "Name":{"Text":[{"Content":"Republican Party","Language":"en"}]}},
            {"@id":"party-lib","@type":"ElectionResults.Party",
             "Name":{"Text":[{"Content":"Libertarian Party","Language":"en"}]}},
            # VIOLATION 5: undefined party "party-green"
            {"@id":"party-green","@type":"ElectionResults.Party",
             "Name":{"Text":[{"Content":"Green Party","Language":"en"}]}},
        ],
    }}


def main():
    os.makedirs(OUTDIR, exist_ok=True)

    bd = build_bd()
    cvr, tallies = build_cvr_and_tallies()
    err = build_err(tallies)

    for name, data in [("bd.json", bd), ("cvr.json", cvr), ("err.json", err)]:
        with open(os.path.join(OUTDIR, name), "w") as f:
            json.dump(data, f, indent=2)
        print(f"Wrote {OUTDIR}/{name}")

    # Verification printout (removed along with this script)
    print("\n=== Computed tallies ===")
    for cid in sorted(tallies):
        for sid in sorted(tallies[cid]):
            print(f"  {cid} / {sid}: {tallies[cid][sid]}")


if __name__ == "__main__":
    main()
