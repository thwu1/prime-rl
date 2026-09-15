#!/usr/bin/env python3
"""SMOKE-compatible chemical speciation for area-source emissions."""

import csv
import os
import sqlite3
import sys


def parse_inventory(path):
    records = []
    year = None
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#YEAR"):
                year = int(line.split()[1])
                continue
            if line.startswith("#"):
                continue
            parts = line.split(",")
            records.append(
                {
                    "country": parts[0].strip(),
                    "region_cd": parts[1].strip(),
                    "scc": parts[5].strip(),
                    "polid": parts[7].strip(),
                    "ann_value": float(parts[8].strip()),
                }
            )
    return records, year


def parse_gsref(path):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(";")]
            entries.append(
                {
                    "scc": parts[0],
                    "profile_code": parts[1],
                    "pollutant": parts[2],
                    "fips": parts[3] if len(parts) > 3 else "",
                }
            )
    return entries


def parse_gspro(path):
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(";")]
            entries.append(
                {
                    "profile_code": parts[0],
                    "pollutant": parts[1],
                    "species_id": parts[2],
                    "split_factor": float(parts[3]),
                    "divisor": float(parts[4]),
                    "mass_fraction": float(parts[5]),
                }
            )
    return entries


def parse_gscnv(path):
    entries = []
    found_header = False
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#BY PROFILE"):
                found_header = True
                continue
            if line.startswith("#"):
                continue
            if found_header:
                parts = [p.strip() for p in line.split(",")]
                entries.append(
                    {
                        "pollutant_from": parts[0],
                        "pollutant_to": parts[1],
                        "profile_code": parts[2],
                        "conversion_factor": float(parts[3]),
                    }
                )
    return entries


def parse_griddesc(path, grid_name):
    """Parse a GRIDDESC file and return grid + coord system parameters.

    Per the I/O API spec, the file begins with one header line (always
    read and ignored), followed by coordinate-system entries (name/params
    pairs) terminated by a blank name, then grid entries (name/params
    pairs) terminated by a blank name.
    """
    with open(path) as f:
        raw_lines = f.readlines()

    # Keep all non-empty lines; inline ! comments handled by parse_tokens.
    # The first line is the header (skipped via idx=1 below).
    lines = []
    for line in raw_lines:
        stripped = line.strip()
        if stripped:
            lines.append(stripped)

    def fortran_float(s):
        """Convert Fortran D-exponent notation to Python float."""
        return float(s.replace("D", "E").replace("d", "e"))

    def parse_tokens(line_text):
        """Split a Fortran list-directed line into tokens."""
        tokens = []
        i = 0
        while i < len(line_text):
            c = line_text[i]
            if c in (" ", ",", "\t"):
                i += 1
                continue
            if c == "'":
                end = line_text.index("'", i + 1)
                tokens.append(line_text[i + 1 : end])
                i = end + 1
            elif c == "!":
                break
            else:
                j = i
                while j < len(line_text) and line_text[j] not in (" ", ",", "\t", "!"):
                    j += 1
                tokens.append(line_text[i:j])
                i = j
        return tokens

    # First line is the header (always ignored per GRIDDESC spec)
    idx = 1

    # Segment 1: Coordinate systems
    coord_systems = {}
    while idx < len(lines):
        tokens = parse_tokens(lines[idx])
        idx += 1
        if not tokens:
            continue
        name = tokens[0].strip()
        if name == "" or name.isspace():
            break
        params = parse_tokens(lines[idx])
        idx += 1
        coord_systems[name] = {
            "coordtype": int(params[0]),
            "p_alp": fortran_float(params[1]),
            "p_bet": fortran_float(params[2]),
            "p_gam": fortran_float(params[3]),
            "xcent": fortran_float(params[4]),
            "ycent": fortran_float(params[5]),
        }

    # Segment 2: Grids
    grids = {}
    while idx < len(lines):
        tokens = parse_tokens(lines[idx])
        idx += 1
        if not tokens:
            continue
        name = tokens[0].strip()
        if name == "" or name.isspace():
            break
        params = parse_tokens(lines[idx])
        idx += 1
        coord_name = params[0].strip()
        grids[name] = {
            "coord_name": coord_name,
            "xorig": fortran_float(params[1]),
            "yorig": fortran_float(params[2]),
            "xcell": fortran_float(params[3]),
            "ycell": fortran_float(params[4]),
            "ncols": int(params[5]),
            "nrows": int(params[6]),
            "nthik": int(params[7]),
        }

    grid = grids[grid_name]
    coord = coord_systems[grid["coord_name"]]
    return grid, coord


def write_ioapi_netcdf(output_path, grid, coord, species_list, sdate):
    """Write an I/O API-conformant NetCDF file."""
    import netCDF4
    import numpy as np

    ds = netCDF4.Dataset(output_path, "w", format="NETCDF3_CLASSIC")

    nvars = len(species_list)

    # Dimensions
    ds.createDimension("TSTEP", None)
    ds.createDimension("DATE-TIME", 2)
    ds.createDimension("LAY", 1)
    ds.createDimension("VAR", nvars)
    ds.createDimension("ROW", grid["nrows"])
    ds.createDimension("COL", grid["ncols"])

    # Global attributes
    ds.IOAPI_VERSION = "3.2"
    ds.EXEC_ID = "speciate"
    ds.FTYPE = np.int32(1)
    ds.CDATE = np.int32(sdate)
    ds.CTIME = np.int32(0)
    ds.WDATE = np.int32(sdate)
    ds.WTIME = np.int32(0)
    ds.SDATE = np.int32(sdate)
    ds.STIME = np.int32(0)
    ds.TSTEP = np.int32(0)
    ds.MXREC = np.int32(1)
    ds.NVARS = np.int32(nvars)
    ds.NCOLS = np.int32(grid["ncols"])
    ds.NROWS = np.int32(grid["nrows"])
    ds.NLAYS = np.int32(1)
    ds.NTHIK = np.int32(grid["nthik"])
    ds.GDTYP = np.int32(coord["coordtype"])
    ds.P_ALP = np.float64(coord["p_alp"])
    ds.P_BET = np.float64(coord["p_bet"])
    ds.P_GAM = np.float64(coord["p_gam"])
    ds.XCENT = np.float64(coord["xcent"])
    ds.YCENT = np.float64(coord["ycent"])
    ds.XORIG = np.float64(grid["xorig"])
    ds.YORIG = np.float64(grid["yorig"])
    ds.XCELL = np.float64(grid["xcell"])
    ds.YCELL = np.float64(grid["ycell"])
    ds.VGTYP = np.int32(-9999)
    ds.VGTOP = np.float32(-9.999e36)
    ds.VGLVLS = np.array([0.0, 0.0], dtype=np.float32)
    ds.GDNAM = "SE_US_12KM".ljust(16)
    ds.UPNAM = "SPECIATE".ljust(16)
    ds.FILEDESC = "Speciated emissions from SMOKE-compatible pipeline"
    ds.HISTORY = ""

    var_list = "".join(sp.ljust(16) for sp in species_list)
    ds.setncattr("VAR-LIST", var_list)

    # TFLAG variable
    tflag = ds.createVariable("TFLAG", "i4", ("TSTEP", "VAR", "DATE-TIME"))
    tflag.units = "<YYYYDDD,HHMMSS>"
    tflag.long_name = "TFLAG"
    tflag_data = np.zeros((1, nvars, 2), dtype=np.int32)
    tflag_data[0, :, 0] = sdate
    tflag_data[0, :, 1] = 0
    tflag[:] = tflag_data

    # Species variables
    for sp in species_list:
        var = ds.createVariable(sp, "f4", ("TSTEP", "LAY", "ROW", "COL"))
        var.long_name = sp.ljust(16)
        var.units = "tons/year".ljust(16)
        var.var_desc = sp.ljust(80)
        var[:] = np.zeros((1, 1, grid["nrows"], grid["ncols"]), dtype=np.float32)

    ds.close()


def country_to_digit(country):
    mapping = {"US": "0", "USA": "0", "CA": "1", "CAN": "1", "MX": "2", "MEX": "2"}
    return mapping.get(country.upper(), "0")


def make_fips6(country, region_cd):
    return country_to_digit(country) + region_cd.zfill(5)


def make_state_fips(fips6):
    return fips6[:3] + "000"


def is_zero_scc(scc):
    return all(c == "0" for c in scc) if scc else True


def is_zero_pollutant(pol):
    return pol == "0" or pol == ""


def match_gsref(gsref_entries, fips6, scc, pollutant):
    state_fips = make_state_fips(fips6)

    # Pollutant-specific tiers (1-6)
    for e in gsref_entries:
        if (
            not is_zero_scc(e["scc"])
            and e["scc"] == scc
            and e["fips"] == fips6
            and not is_zero_pollutant(e["pollutant"])
            and e["pollutant"] == pollutant
        ):
            return e

    for e in gsref_entries:
        if (
            not is_zero_scc(e["scc"])
            and e["scc"] == scc
            and e["fips"] == state_fips
            and not is_zero_pollutant(e["pollutant"])
            and e["pollutant"] == pollutant
        ):
            return e

    for e in gsref_entries:
        if (
            not is_zero_scc(e["scc"])
            and e["scc"] == scc
            and e["fips"] == ""
            and not is_zero_pollutant(e["pollutant"])
            and e["pollutant"] == pollutant
        ):
            return e

    for e in gsref_entries:
        if (
            is_zero_scc(e["scc"])
            and e["fips"] == fips6
            and not is_zero_pollutant(e["pollutant"])
            and e["pollutant"] == pollutant
        ):
            return e

    for e in gsref_entries:
        if (
            is_zero_scc(e["scc"])
            and e["fips"] == state_fips
            and not is_zero_pollutant(e["pollutant"])
            and e["pollutant"] == pollutant
        ):
            return e

    for e in gsref_entries:
        if (
            is_zero_scc(e["scc"])
            and e["fips"] == ""
            and not is_zero_pollutant(e["pollutant"])
            and e["pollutant"] == pollutant
        ):
            return e

    # Non-pollutant-specific tiers (7-12)
    for e in gsref_entries:
        if (
            not is_zero_scc(e["scc"])
            and e["scc"] == scc
            and e["fips"] == fips6
            and is_zero_pollutant(e["pollutant"])
        ):
            return e

    for e in gsref_entries:
        if (
            not is_zero_scc(e["scc"])
            and e["scc"] == scc
            and e["fips"] == state_fips
            and is_zero_pollutant(e["pollutant"])
        ):
            return e

    for e in gsref_entries:
        if (
            not is_zero_scc(e["scc"])
            and e["scc"] == scc
            and e["fips"] == ""
            and is_zero_pollutant(e["pollutant"])
        ):
            return e

    for e in gsref_entries:
        if (
            is_zero_scc(e["scc"])
            and e["fips"] == fips6
            and is_zero_pollutant(e["pollutant"])
        ):
            return e

    for e in gsref_entries:
        if (
            is_zero_scc(e["scc"])
            and e["fips"] == state_fips
            and is_zero_pollutant(e["pollutant"])
        ):
            return e

    for e in gsref_entries:
        if (
            is_zero_scc(e["scc"])
            and e["fips"] == ""
            and is_zero_pollutant(e["pollutant"])
        ):
            return e

    return None


def main():
    data_dir = "/app/data"
    output_dir = "/app/output"
    os.makedirs(output_dir, exist_ok=True)

    inventory, year = parse_inventory(os.path.join(data_dir, "inventory.ff10"))
    gsref = parse_gsref(os.path.join(data_dir, "gsref.txt"))
    gspro = parse_gspro(os.path.join(data_dir, "gspro.txt"))
    gscnv = parse_gscnv(os.path.join(data_dir, "gscnv.txt"))

    gspro_index = {}
    for entry in gspro:
        key = (entry["profile_code"], entry["pollutant"])
        gspro_index.setdefault(key, []).append(entry)

    gscnv_index = {}
    for entry in gscnv:
        key = (entry["profile_code"], entry["pollutant_from"])
        gscnv_index[key] = entry

    output_rows = []
    diag_rows = []

    for rec in inventory:
        fips6 = make_fips6(rec["country"], rec["region_cd"])
        match = match_gsref(gsref, fips6, rec["scc"], rec["polid"])
        if match is None:
            print(f"WARNING: No GSREF match for {rec}", file=sys.stderr)
            continue

        profile_code = match["profile_code"]
        emissions = rec["ann_value"]
        lookup_pollutant = rec["polid"]

        diag_rows.append(
            {
                "REGION_CD": rec["region_cd"],
                "SCC": rec["scc"],
                "POLID": rec["polid"],
                "PROFILE_CODE": profile_code,
                "GSREF_SCC": match["scc"],
                "GSREF_FIPS": match["fips"],
                "GSREF_POLLUTANT": match["pollutant"],
            }
        )

        cnv_key = (profile_code, rec["polid"])
        if cnv_key in gscnv_index:
            cnv = gscnv_index[cnv_key]
            emissions = emissions * cnv["conversion_factor"]
            lookup_pollutant = cnv["pollutant_to"]

        gspro_key = (profile_code, lookup_pollutant)
        if gspro_key not in gspro_index:
            print(f"WARNING: No GSPRO for {gspro_key}", file=sys.stderr)
            continue

        for sp in gspro_index[gspro_key]:
            mass_tons = sp["mass_fraction"] * emissions
            mole_amount = (sp["split_factor"] / sp["divisor"]) * emissions
            output_rows.append(
                {
                    "REGION_CD": rec["region_cd"],
                    "SCC": rec["scc"],
                    "POLID": rec["polid"],
                    "SPECIES_ID": sp["species_id"],
                    "PROFILE_CODE": profile_code,
                    "MASS_TONS": f"{mass_tons:.4f}",
                    "MOLE_AMOUNT": f"{mole_amount:.4f}",
                }
            )

    output_rows.sort(
        key=lambda r: (r["REGION_CD"], r["SCC"], r["POLID"], r["SPECIES_ID"])
    )
    diag_rows.sort(key=lambda r: (r["REGION_CD"], r["SCC"], r["POLID"]))

    # Write speciated CSV
    output_path = os.path.join(output_dir, "speciated.csv")
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "REGION_CD",
                "SCC",
                "POLID",
                "SPECIES_ID",
                "PROFILE_CODE",
                "MASS_TONS",
                "MOLE_AMOUNT",
            ],
        )
        writer.writeheader()
        writer.writerows(output_rows)

    # Write diagnostics CSV
    diag_path = os.path.join(output_dir, "diagnostics.csv")
    with open(diag_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "REGION_CD",
                "SCC",
                "POLID",
                "PROFILE_CODE",
                "GSREF_SCC",
                "GSREF_FIPS",
                "GSREF_POLLUTANT",
            ],
        )
        writer.writeheader()
        writer.writerows(diag_rows)

    # Write SQLite database
    db_path = os.path.join(output_dir, "speciation.db")
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        "CREATE TABLE inventory ("
        "region_cd TEXT, scc TEXT, polid TEXT, ann_value REAL"
        ")"
    )
    for rec in inventory:
        cur.execute(
            "INSERT INTO inventory VALUES (?, ?, ?, ?)",
            (rec["region_cd"], rec["scc"], rec["polid"], rec["ann_value"]),
        )

    cur.execute(
        "CREATE TABLE speciated ("
        "region_cd TEXT, scc TEXT, polid TEXT, species_id TEXT, "
        "profile_code TEXT, mass_tons REAL, mole_amount REAL"
        ")"
    )
    for row in output_rows:
        cur.execute(
            "INSERT INTO speciated VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["REGION_CD"],
                row["SCC"],
                row["POLID"],
                row["SPECIES_ID"],
                row["PROFILE_CODE"],
                float(row["MASS_TONS"]),
                float(row["MOLE_AMOUNT"]),
            ),
        )

    cur.execute(
        "CREATE TABLE match_log ("
        "region_cd TEXT, scc TEXT, polid TEXT, profile_code TEXT, "
        "gsref_scc TEXT, gsref_fips TEXT, gsref_pollutant TEXT"
        ")"
    )
    for d in diag_rows:
        cur.execute(
            "INSERT INTO match_log VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                d["REGION_CD"],
                d["SCC"],
                d["POLID"],
                d["PROFILE_CODE"],
                d["GSREF_SCC"],
                d["GSREF_FIPS"],
                d["GSREF_POLLUTANT"],
            ),
        )

    cur.execute(
        "CREATE INDEX idx_speciated_lookup "
        "ON speciated(region_cd, scc, polid, species_id)"
    )
    conn.commit()
    conn.close()

    # Collect unique species and write NetCDF
    species_set = set()
    for row in output_rows:
        species_set.add(row["SPECIES_ID"])
    species_list = sorted(species_set)

    sdate = year * 1000 + 1  # YYYYDDD format

    grid, coord = parse_griddesc(
        os.path.join(data_dir, "griddesc.txt"), "SE_US_12KM"
    )
    nc_path = os.path.join(output_dir, "emissions.nc")
    write_ioapi_netcdf(nc_path, grid, coord, species_list, sdate)

    print(f"Wrote {len(output_rows)} speciated records to {output_path}")
    print(f"Wrote {len(diag_rows)} diagnostic records to {diag_path}")
    print(f"Wrote SQLite database to {db_path}")
    print(f"Wrote I/O API NetCDF to {nc_path}")


if __name__ == "__main__":
    main()
