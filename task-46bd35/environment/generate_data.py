#!/usr/bin/env python3
"""Generate HMDA filing test data with seeded validation errors."""
import os

LEI = "TBFN0123456789ABCDEF"  # Exactly 20 characters


def make_base_lar_fields(uli_suffix):
    """Create a valid base LAR record as a list of 110 field values."""
    uli = LEI + uli_suffix

    f = [""] * 110

    # Identification (Fields 1-4)
    f[0] = "2"
    f[1] = LEI
    f[2] = uli
    f[3] = "20240315"

    # Loan Details (Fields 5-12)
    f[4] = "1"           # Loan Type: Conventional
    f[5] = "1"           # Loan Purpose: Home purchase
    f[6] = "2"           # Preapproval: Not requested
    f[7] = "1"           # Construction Method: Site-built
    f[8] = "1"           # Occupancy Type: Principal
    f[9] = "250000"      # Loan Amount
    f[10] = "1"          # Action Taken: Originated
    f[11] = "20240401"   # Action Taken Date

    # Geography (Fields 13-18)
    f[12] = "123 Main St"
    f[13] = "Anytown"
    f[14] = "CA"
    f[15] = "90210"
    f[16] = "06037"
    f[17] = "06037264000"

    # Ethnicity Applicant (Fields 19-24): 6 fields
    f[18] = "2"   # Not Hispanic or Latino

    # Ethnicity Co-Applicant (Fields 25-30): 6 fields
    f[24] = "2"   # Not Hispanic or Latino

    # Ethnicity Observed (Fields 31-32)
    f[30] = "2"
    f[31] = "2"

    # Race Applicant (Fields 33-37): 5 fields
    f[32] = "5"   # White

    # Race Applicant Free Form (Fields 38-40): 3 fields - blank

    # Race Co-Applicant (Fields 41-45): 5 fields
    f[40] = "5"   # White

    # Race Co-App Free Form (Fields 46-48): 3 fields - blank

    # Race Observed (Fields 49-50)
    f[48] = "2"
    f[49] = "2"

    # Sex (Fields 51-54)
    f[50] = "1"   # Male
    f[51] = "5"   # No co-applicant
    f[52] = "2"   # Not observed
    f[53] = "4"   # No co-applicant

    # Age (Fields 55-56)
    f[54] = "35"
    f[55] = "9999"  # No co-applicant

    # Income through Lien Status (Fields 57-61)
    f[56] = "75"
    f[57] = "0"     # Purchaser Type: NA
    f[58] = "NA"    # Rate Spread
    f[59] = "2"     # HOEPA Status: Not high-cost
    f[60] = "1"     # Lien Status: First lien

    # Credit Score (Fields 62-67)
    f[61] = "720"
    f[62] = "9999"  # No co-applicant
    f[63] = "1"     # Equifax Beacon 5.0
    # f[64] blank
    f[65] = "10"    # No co-applicant
    # f[66] blank

    # Denial Reasons (Fields 68-72)
    f[67] = "10"    # Not applicable

    # Loan Costs (Fields 73-77)
    f[72] = "NA"
    f[73] = "NA"
    f[74] = "NA"

    # Interest/DTI (Fields 78-83)
    f[77] = "4.5"
    f[78] = "NA"
    f[79] = "42"
    f[80] = "80"
    f[81] = "360"
    f[82] = "NA"

    # Non-Amortizing (Fields 84-87)
    f[83] = "2"
    f[84] = "2"
    f[85] = "2"
    f[86] = "2"

    # Property (Fields 88-92)
    f[87] = "350000"
    f[88] = "3"     # NA
    f[89] = "5"     # NA
    f[90] = "1"     # 1 unit
    f[91] = "NA"

    # Application (Fields 93-95)
    f[92] = "1"     # Direct
    f[93] = "1"     # Payable to institution
    f[94] = "12345" # NMLSR

    # AUS (Fields 96-101)
    f[95] = "6"     # Not applicable

    # AUS Result (Fields 102-107)
    f[101] = "17"   # Not applicable

    # Reverse/LOC/Biz (Fields 108-110)
    f[107] = "2"    # Not reverse mortgage
    f[108] = "2"    # Not open-end LOC
    f[109] = "2"    # Not business/commercial

    return f


def make_lar(uli_suffix, overrides=None):
    """Create a LAR record line with optional field overrides (0-indexed)."""
    fields = make_base_lar_fields(uli_suffix)
    if overrides:
        for idx, val in overrides.items():
            fields[idx] = val
    assert len(fields) == 110, f"Expected 110 fields, got {len(fields)}"
    return "|".join(fields)


def make_ts():
    """Create the Transmittal Sheet record with intentional errors."""
    fields = [
        "1",                    # Field 1: Record ID
        "TestBank Financial",   # Field 2: Institution Name
        "2024",                 # Field 3: Calendar Year
        "4",                    # Field 4: Quarter
        "John Smith",           # Field 5: Contact Name
        "555-123-4567",         # Field 6: Contact Phone
        "john@testbank.com",    # Field 7: Contact Email
        "100 Main Street",      # Field 8: Street
        "Anytown",              # Field 9: City
        "CA",                   # Field 10: State
        "90210",                # Field 11: ZIP
        "4",                    # Field 12: Agency (ERROR: 4 not in {1,2,3,5,7,9})
        "10",                   # Field 13: Total Lines (ERROR: actual is 12)
        "99-1234567",           # Field 14: Tax ID
        LEI,                    # Field 15: LEI
    ]
    assert len(fields) == 15, f"TS has {len(fields)} fields, expected 15"
    return "|".join(fields)


def main():
    os.makedirs("/app", exist_ok=True)

    ts_line = make_ts()

    lar_lines = [
        # LAR-01: Valid record - no errors
        make_lar("00001"),

        # LAR-02: S301 (LEI mismatch with TS)
        make_lar("00002", {
            1: "WRONGLEI456789ABCDEF",
            2: "WRONGLEI456789ABCDEF00002",
        }),

        # LAR-03: V608_1 (ULI doesn't start with record's LEI)
        make_lar("00003", {
            2: "ZZZZ0123456789ABCDEF00003",
        }),

        # LAR-04: V611 (loan type=5 invalid), V612_1 (loan purpose=6 invalid)
        make_lar("00004", {
            4: "5",
            5: "6",
        }),

        # LAR-05: V610_1 (invalid app date - month 13, day 45)
        make_lar("00005", {
            3: "20241345",
        }),

        # LAR-06: Q617 (action date 20240101 before app date 20240601)
        make_lar("00006", {
            3: "20240601",
            11: "20240101",
        }),

        # LAR-07: S305 (duplicate ULI - same as LAR-01)
        make_lar("00001"),

        # LAR-08: V620 (action=7 requires preapproval=1, but preapproval=2)
        make_lar("00008", {
            10: "7",
        }),

        # LAR-09: V619_1 (preapproval=1 but action=6 not in allowed set)
        make_lar("00009", {
            6: "1",
            10: "6",
        }),

        # LAR-10: V636_1 (sex=9 invalid), V661 (lien=3 invalid)
        make_lar("00010", {
            50: "9",
            60: "3",
        }),

        # LAR-11: Q601 (loan amount 50M exceeds 10M threshold)
        make_lar("00011", {
            9: "50000000",
        }),

        # LAR-12: V609 (ULI 22 chars, min 23), V614_1 (construction=3),
        #         V615_1 (occupancy=4), V616 (amount=0), V618 (bad action date)
        make_lar("ZZ", {
            7: "3",
            8: "4",
            9: "0",
            11: "20241301",
        }),
    ]

    # Verify field counts
    ts_check = ts_line.split("|")
    assert len(ts_check) == 15, f"TS has {len(ts_check)} fields"
    for i, lar in enumerate(lar_lines):
        lar_check = lar.split("|")
        assert len(lar_check) == 110, f"LAR-{i+1} has {len(lar_check)} fields"

    with open("/app/filing.txt", "w") as f:
        f.write(ts_line + "\n")
        for lar in lar_lines:
            f.write(lar + "\n")

    print(f"Generated filing: 1 TS + {len(lar_lines)} LARs")
    print(f"TS total_lines=10, actual={len(lar_lines)}")
    print("Errors seeded: S301, S304, S305, V607, V608_1, V609, V610_1,")
    print("  V611, V612_1, V614_1, V615_1, V616, V618, V619_1, V620,")
    print("  V636_1, V661, Q601, Q617")


if __name__ == "__main__":
    main()
