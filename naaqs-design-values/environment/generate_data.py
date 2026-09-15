#!/usr/bin/env python3
"""Generate synthetic EPA AQS annual summary data for NAAQS design value task."""
import csv
import os

HEADERS = [
    "State Code", "County Code", "Site Num", "Parameter Code", "POC",
    "Latitude", "Longitude", "Datum", "Parameter Name", "Sample Duration",
    "Pollutant Standard", "Metric Used", "Method Name", "Year", "Units of Measure",
    "Event Type", "Observation Count", "Observation Percent", "Completeness Indicator",
    "Valid Day Count", "Required Day Count", "Exceptional Data Count", "Null Data Count",
    "Primary Exceedance Count", "Secondary Exceedance Count", "Certification Indicator",
    "Num Obs Below MDL", "Arithmetic Mean", "Arithmetic Standard Dev",
    "1st Max Value", "1st Max DateTime", "2nd Max Value", "2nd Max DateTime",
    "3rd Max Value", "3rd Max DateTime", "4th Max Value", "4th Max DateTime",
    "1st Max Non Overlapping Value", "1st NO Max DateTime",
    "2nd Max Non Overlapping Value", "2nd NO Max DateTime",
    "99th Percentile", "98th Percentile", "95th Percentile", "90th Percentile",
    "75th Percentile", "50th Percentile", "10th Percentile",
    "Local Site Name", "Address", "State Name", "County Name", "City Name",
    "CBSA Name", "Date of Last Change"
]

# Pollutant configs: (param_code, param_name, sample_dur, poll_std, metric_used, method_name, units)
O3 = ("44201", "Ozone", "8-HR RUN AVG BEGIN", "Ozone 8-hour 2015",
      "Daily Maximum", "INSTRUMENTAL - ULTRA VIOLET ABSORPTION", "Parts per million")
PM25A = ("88101", "PM2.5 - Local Conditions", "24 HOUR", "PM25 Annual 2024",
         "Observed Values", "GRAVIMETRIC-Fed Ref Method-Loss Compensated",
         "Micrograms/cubic meter (25 C)")
PM25D = ("88101", "PM2.5 - Local Conditions", "24 HOUR", "PM25 24-hour 2024",
         "Observed Values", "GRAVIMETRIC-Fed Ref Method-Loss Compensated",
         "Micrograms/cubic meter (25 C)")
NO2 = ("42602", "Nitrogen dioxide (NO2)", "1 HOUR", "NO2 1-hour",
       "Daily Maximum", "INSTRUMENTAL - CHEMILUMINESCENCE", "Parts per billion")
SO2 = ("42401", "Sulfur dioxide", "1 HOUR", "SO2 1-hour 2010",
       "Daily Maximum", "INSTRUMENTAL - ULTRAVIOLET FLUORESCENCE", "Parts per billion")
CO = ("42101", "Carbon monoxide", "8-HR RUN AVG END", "CO 8-hour 1971",
      "Running Average", "INSTRUMENTAL - NONDISPERSIVE INFRARED", "Parts per million")

# Sites: (state, county, site, lat, lon, state_name, county_name, city_name, cbsa_name)
LA = ("06", "037", "0002", 34.06653, -118.22676, "California", "Los Angeles",
      "Los Angeles", "Los Angeles-Long Beach-Anaheim, CA")
NYC = ("36", "061", "0056", 40.81614, -73.90198, "New York", "New York",
       "New York", "New York-Newark-Jersey City, NY-NJ-PA")
PHX = ("04", "013", "0019", 33.47972, -112.14250, "Arizona", "Maricopa",
       "Phoenix", "Phoenix-Mesa-Scottsdale, AZ")
CHI = ("17", "031", "4201", 41.75138, -87.71339, "Illinois", "Cook",
       "Chicago", "Chicago-Naperville-Elgin, IL-IN-WI")
HOU = ("48", "201", "1039", 29.67012, -95.12849, "Texas", "Harris",
       "Houston", "Houston-The Woodlands-Sugar Land, TX")
LA2 = ("06", "037", "1103", 34.01014, -118.06009, "California", "Los Angeles",
       "Pico Rivera", "Los Angeles-Long Beach-Anaheim, CA")
PIT = ("42", "003", "0008", 40.44957, -79.96071, "Pennsylvania", "Allegheny",
       "Pittsburgh", "Pittsburgh, PA")
STL = ("29", "510", "0085", 38.63011, -90.19778, "Missouri", "St. Louis city",
       "St. Louis", "St. Louis, MO-IL")


def make_row(site, poll, poc, year, et="No Events", oc=8000, op=95.0,
             ci="Y", vd=347, rd=365, ed=0, nd=0, pe=0, se=0,
             mean=0, sd=0,
             m1="", m2="", m3="", m4="",
             nm1="", nm2="",
             p99="", p98="", p95="", p90="", p75="", p50="", p10=""):
    st, co, si, lat, lon, sn, cn, ctn, cbsa = site
    pc, pn, sdur, ps, mu, mn, units = poll

    def dt(v, dflt):
        return "{}-{}".format(year, dflt) if v != "" else ""

    return [
        st, co, si, pc, poc, lat, lon, "NAD83", pn, sdur,
        ps, mu, mn, year, units,
        et, oc, op, ci, vd, rd, ed, nd, pe, se,
        "Certified", 0, mean, sd,
        m1, dt(m1, "07-15 14:00"), m2, dt(m2, "08-02 13:00"),
        m3, dt(m3, "06-22 15:00"), m4, dt(m4, "09-10 14:00"),
        nm1, dt(nm1, "12-15 08:00"), nm2, dt(nm2, "01-22 07:00"),
        p99, p98, p95, p90, p75, p50, p10,
        "", "", sn, cn, ctn, cbsa, "2024-05-01"
    ]


rows = []

# === O3 at LA (06-037-0002) ===
# DV = trunc3((0.079+0.073+0.069)/3) = trunc3(0.07367) = 0.073 > 0.070 => EXCEEDS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 0.042, 0.018, 0.098, 0.092, 0.085, 0.079, 0.081, 0.076, 0.068, 0.062, 0.051, 0.040, 0.020),
    (2022, 0.040, 0.017, 0.091, 0.086, 0.079, 0.073, 0.078, 0.074, 0.066, 0.060, 0.049, 0.038, 0.018),
    (2023, 0.038, 0.016, 0.088, 0.081, 0.075, 0.069, 0.075, 0.070, 0.064, 0.058, 0.047, 0.036, 0.016),
]:
    rows.append(make_row(LA, O3, 1, yr, mean=mn, sd=s,
                         m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === O3 at NYC (36-061-0056) ===
# DV = trunc3((0.068+0.071+0.065)/3) = trunc3(0.068) = 0.068 <= 0.070 => MEETS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 0.035, 0.015, 0.085, 0.078, 0.072, 0.068, 0.072, 0.067, 0.060, 0.055, 0.044, 0.033, 0.015),
    (2022, 0.037, 0.016, 0.089, 0.082, 0.076, 0.071, 0.075, 0.070, 0.063, 0.057, 0.046, 0.035, 0.017),
    (2023, 0.034, 0.014, 0.082, 0.075, 0.069, 0.065, 0.069, 0.065, 0.058, 0.053, 0.043, 0.032, 0.014),
]:
    rows.append(make_row(NYC, O3, 1, yr, mean=mn, sd=s,
                         m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === O3 at Phoenix (04-013-0019) — 2021 incomplete ===
# DV = trunc3((0.082+0.075+0.071)/3) = trunc3(0.076) = 0.076 > 0.070 => EXCEEDS, incomplete
for yr, mn, s, m1, m2, m3, m4, ci_, op_, vd_, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 0.045, 0.022, 0.102, 0.095, 0.088, 0.082, "N", 55.0, 201,
     0.090, 0.085, 0.075, 0.068, 0.055, 0.043, 0.022),
    (2022, 0.043, 0.020, 0.094, 0.087, 0.081, 0.075, "Y", 95.0, 347,
     0.082, 0.077, 0.069, 0.063, 0.053, 0.041, 0.020),
    (2023, 0.041, 0.019, 0.089, 0.082, 0.076, 0.071, "Y", 95.0, 347,
     0.078, 0.073, 0.066, 0.061, 0.050, 0.039, 0.019),
]:
    rows.append(make_row(PHX, O3, 1, yr, ci=ci_, op=op_, vd=vd_,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === PM2.5 Annual at Chicago (17-031-4201) ===
# DV = round1((10.2+9.8+8.5)/3) = round1(9.5) = 9.5 > 9.0 => EXCEEDS
# NOTE: 2022 has both "No Events" (mean=9.8) and "Events Included" (mean=11.2) rows
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10, et in [
    (2021, 10.2, 5.1, 45.8, 42.3, 39.7, 37.2, 42.1, 38.2, 28.5, 20.1, 12.4, 8.7, 3.2, "No Events"),
    (2022,  9.8, 4.8, 43.1, 40.2, 37.8, 35.4, 40.5, 35.6, 26.8, 19.3, 11.9, 8.4, 3.0, "No Events"),
    (2022, 11.2, 5.5, 52.4, 48.1, 44.7, 41.3, 48.5, 43.2, 32.1, 22.5, 13.8, 9.6, 3.5, "Events Included"),
    (2023,  8.5, 4.2, 38.9, 36.1, 33.5, 31.2, 36.8, 33.1, 24.2, 17.5, 10.3, 7.2, 2.6, "No Events"),
]:
    rows.append(make_row(CHI, PM25A, 1, yr, et=et,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === PM2.5 24-hour at Chicago (17-031-4201) ===
# DV = round0((38.2+35.6+33.1)/3) = round0(35.633) = 36 > 35 => EXCEEDS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 10.2, 5.1, 45.8, 42.3, 39.7, 37.2, 42.1, 38.2, 28.5, 20.1, 12.4, 8.7, 3.2),
    (2022,  9.8, 4.8, 43.1, 40.2, 37.8, 35.4, 40.5, 35.6, 26.8, 19.3, 11.9, 8.4, 3.0),
    (2023,  8.5, 4.2, 38.9, 36.1, 33.5, 31.2, 36.8, 33.1, 24.2, 17.5, 10.3, 7.2, 2.6),
]:
    rows.append(make_row(CHI, PM25D, 1, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === PM2.5 Annual at Houston (48-201-1039) ===
# DV = round1((8.7+9.1+8.6)/3) = round1(8.8) = 8.8 <= 9.0 => MEETS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 8.7, 4.0, 35.2, 32.8, 30.1, 28.5, 33.1, 32.4, 22.1, 16.8, 10.5, 7.5, 2.8),
    (2022, 9.1, 4.3, 38.5, 35.9, 33.2, 31.0, 36.2, 34.8, 24.5, 18.1, 11.2, 7.9, 3.0),
    (2023, 8.6, 3.9, 33.8, 31.5, 29.0, 27.3, 31.9, 30.2, 21.3, 16.2, 10.1, 7.3, 2.7),
]:
    rows.append(make_row(HOU, PM25A, 1, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === PM2.5 24-hour at Houston (48-201-1039) ===
# DV = round0((32.4+34.8+30.2)/3) = round0(32.467) = 32 <= 35 => MEETS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 8.7, 4.0, 35.2, 32.8, 30.1, 28.5, 33.1, 32.4, 22.1, 16.8, 10.5, 7.5, 2.8),
    (2022, 9.1, 4.3, 38.5, 35.9, 33.2, 31.0, 36.2, 34.8, 24.5, 18.1, 11.2, 7.9, 3.0),
    (2023, 8.6, 3.9, 33.8, 31.5, 29.0, 27.3, 31.9, 30.2, 21.3, 16.2, 10.1, 7.3, 2.7),
]:
    rows.append(make_row(HOU, PM25D, 1, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === PM2.5 Annual at LA2 (06-037-1103) POC 1 ===
# DV = round1((11.3+10.8+10.1)/3) = round1(10.733) = 10.7 > 9.0 => EXCEEDS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 11.3, 5.8, 48.2, 44.5, 41.8, 39.1, 45.1, 40.8, 30.2, 21.8, 13.5, 9.5, 3.5),
    (2022, 10.8, 5.4, 45.9, 42.1, 39.5, 37.0, 42.8, 38.9, 28.8, 20.5, 12.9, 9.1, 3.3),
    (2023, 10.1, 5.0, 42.5, 39.2, 36.8, 34.5, 39.8, 36.2, 26.5, 19.0, 12.0, 8.5, 3.0),
]:
    rows.append(make_row(LA2, PM25A, 1, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === PM2.5 Annual at LA2 (06-037-1103) POC 2 ===
# DV = round1((11.0+10.5+9.8)/3) = round1(10.433) = 10.4 > 9.0 => EXCEEDS
# Site-level DV = max(10.7, 10.4) = 10.7 from POC 1
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 11.0, 5.6, 47.1, 43.8, 41.0, 38.5, 44.2, 40.0, 29.5, 21.2, 13.2, 9.3, 3.4),
    (2022, 10.5, 5.2, 44.8, 41.5, 38.9, 36.4, 41.9, 38.2, 28.1, 20.0, 12.5, 8.8, 3.2),
    (2023,  9.8, 4.8, 41.2, 38.0, 35.8, 33.5, 38.5, 35.0, 25.8, 18.5, 11.5, 8.2, 2.9),
]:
    rows.append(make_row(LA2, PM25A, 2, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === NO2 1-hour at LA (06-037-0002) ===
# DV = round0((105+98+102)/3) = round0(101.667) = 102 > 100 => EXCEEDS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 22.5, 18.3, 145, 138, 125, 118, 120, 105, 75, 52, 28, 18, 5),
    (2022, 20.8, 16.9, 135, 128, 115, 108, 112,  98, 68, 48, 25, 16, 4),
    (2023, 21.5, 17.5, 140, 132, 120, 113, 115, 102, 72, 50, 27, 17, 5),
]:
    rows.append(make_row(LA, NO2, 1, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === NO2 1-hour at NYC (36-061-0056) ===
# DV = round0((89+95+92)/3) = round0(92) = 92 <= 100 => MEETS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 18.2, 14.5, 120, 112, 105, 98, 102, 89, 58, 42, 22, 14, 4),
    (2022, 19.5, 15.8, 128, 118, 110, 105, 108, 95, 64, 46, 24, 15, 4),
    (2023, 18.8, 15.0, 124, 115, 108, 101, 105, 92, 61, 44, 23, 15, 4),
]:
    rows.append(make_row(NYC, NO2, 1, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === SO2 1-hour at Pittsburgh (42-003-0008) ===
# DV = round0((82+76+71)/3) = round0(76.333) = 76 > 75 => EXCEEDS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 5.2, 8.5, 125, 112, 98, 89, 82, 62, 25, 15, 5, 3, 1),
    (2022, 4.8, 7.9, 118, 105, 92, 85, 76, 58, 22, 13, 4, 2, 0),
    (2023, 4.5, 7.2, 108,  98, 86, 78, 71, 54, 20, 12, 4, 2, 0),
]:
    rows.append(make_row(PIT, SO2, 1, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === SO2 1-hour at St. Louis (29-510-0085) ===
# DV = round0((68+72+65)/3) = round0(68.333) = 68 <= 75 => MEETS
for yr, mn, s, m1, m2, m3, m4, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 3.8, 6.2, 98, 88, 79, 72, 68, 52, 18, 11, 4, 2, 0),
    (2022, 4.1, 6.8, 105, 95, 85, 78, 72, 56, 20, 12, 4, 2, 0),
    (2023, 3.5, 5.8, 92, 82, 74, 68, 65, 48, 16, 10, 3, 2, 0),
]:
    rows.append(make_row(STL, SO2, 1, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# === CO 8-hour at LA (06-037-0002) ===
# DV = max(3.2, 2.8, 3.5) = 3.5 <= 9.0 => MEETS
for yr, mn, s, m1, m2, m3, m4, nm1, nm2, p99, p98, p95, p90, p75, p50, p10 in [
    (2021, 0.8, 0.5, 5.2, 4.8, 4.5, 3.9, 4.5, 3.2, 3.8, 3.2, 2.1, 1.5, 0.9, 0.6, 0.2),
    (2022, 0.7, 0.4, 4.5, 4.1, 3.8, 3.2, 3.9, 2.8, 3.4, 2.9, 1.8, 1.3, 0.8, 0.5, 0.2),
    (2023, 0.9, 0.6, 5.8, 5.3, 4.9, 4.2, 5.1, 3.5, 4.2, 3.6, 2.4, 1.7, 1.0, 0.7, 0.3),
]:
    rows.append(make_row(LA, CO, 1, yr,
                         mean=mn, sd=s, m1=m1, m2=m2, m3=m3, m4=m4,
                         nm1=nm1, nm2=nm2,
                         p99=p99, p98=p98, p95=p95, p90=p90, p75=p75, p50=p50, p10=p10))

# Write output
os.makedirs("/app/data", exist_ok=True)
with open("/app/data/annual_summary_2021_2023.csv", "w", newline="") as f:
    w = csv.writer(f, quoting=csv.QUOTE_ALL)
    w.writerow(HEADERS)
    w.writerows(rows)

print("Generated {} records in /app/data/annual_summary_2021_2023.csv".format(len(rows)))
