-- Signal Analysis Pipeline Solution

-- =========================================================================
-- 1. Create PostgreSQL functions for knowledge base formulas
-- =========================================================================

-- SNQI: Signal-to-Noise Quality Indicator (KB id 0)
-- SNQI = SnrRatio - 0.1 * |NoiseFloorDbm|
CREATE OR REPLACE FUNCTION calculate_snqi(
    p_snr_ratio NUMERIC,
    p_noise_floor DOUBLE PRECISION
) RETURNS NUMERIC AS $$
BEGIN
    RETURN p_snr_ratio - 0.1 * ABS(p_noise_floor);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- AOI: Atmospheric Observability Index (KB id 1)
-- AOI = AtmosTransparency * (1 - HumidityRate/100) * (1 - 0.02 * WindSpeedMs)
CREATE OR REPLACE FUNCTION calculate_aoi(
    p_atmos_transparency NUMERIC,
    p_humidity_rate NUMERIC,
    p_wind_speed_ms NUMERIC
) RETURNS NUMERIC AS $$
BEGIN
    RETURN p_atmos_transparency * (1.0 - p_humidity_rate / 100.0) * (1.0 - 0.02 * p_wind_speed_ms);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- TOLS: Technological Origin Likelihood Score (KB id 3)
-- TOLS = TechSigProb * (1 - NatSrcProb) * SigUnique * (0.5 + AnomScore/10)
CREATE OR REPLACE FUNCTION calculate_tols(
    p_tech_sig_prob NUMERIC,
    p_nat_src_prob NUMERIC,
    p_sig_unique NUMERIC,
    p_anom_score DOUBLE PRECISION
) RETURNS NUMERIC AS $$
BEGIN
    RETURN p_tech_sig_prob * (1.0 - p_nat_src_prob) * p_sig_unique * (0.5 + p_anom_score / 10.0);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- BFR: Bandwidth-Frequency Ratio (KB id 4)
-- BFR = BwHz / (CenterFreqMhz * 10^6)
CREATE OR REPLACE FUNCTION calculate_bfr(
    p_bw_hz NUMERIC,
    p_center_freq_mhz NUMERIC
) RETURNS NUMERIC AS $$
BEGIN
    RETURN p_bw_hz / (p_center_freq_mhz * 1000000.0);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- LIF: Lunar Interference Factor (KB id 9)
-- LIF = (1 - LunarDistDeg/180) * (1 - AtmosTransparency)
CREATE OR REPLACE FUNCTION calculate_lif(
    p_lunar_dist_deg NUMERIC,
    p_atmos_transparency NUMERIC
) RETURNS NUMERIC AS $$
BEGIN
    RETURN (1.0 - p_lunar_dist_deg / 180.0) * (1.0 - p_atmos_transparency);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- RPI: Research Priority Index (KB id 8)
-- RPI = (TechSigProb*4 + BioSigProb/100 + SigUnique*2 + AnomScore/2) * (1 - FalsePosProb)
CREATE OR REPLACE FUNCTION calculate_rpi(
    p_tech_sig_prob NUMERIC,
    p_bio_sig_prob NUMERIC,
    p_sig_unique NUMERIC,
    p_anom_score DOUBLE PRECISION,
    p_false_pos_prob NUMERIC
) RETURNS NUMERIC AS $$
BEGIN
    RETURN (p_tech_sig_prob * 4.0 + p_bio_sig_prob / 100.0 + p_sig_unique * 2.0 + p_anom_score / 2.0)
           * (1.0 - p_false_pos_prob);
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- OQF: Observation Quality Factor (KB id 32, depends on AOI and LIF)
-- OQF = AOI * (1 - LIF) * (PointAccArc < 2 ? 1 : 2/PointAccArc)
CREATE OR REPLACE FUNCTION calculate_oqf(
    p_aoi NUMERIC,
    p_lif NUMERIC,
    p_point_acc_arc NUMERIC
) RETURNS NUMERIC AS $$
BEGIN
    RETURN p_aoi * (1.0 - p_lif)
           * CASE WHEN p_point_acc_arc < 2 THEN 1.0 ELSE 2.0 / p_point_acc_arc END;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- =========================================================================
-- 2. Create materialized view joining signals with related tables
-- =========================================================================

DROP MATERIALIZED VIEW IF EXISTS mv_signal_analysis;

CREATE MATERIALIZED VIEW mv_signal_analysis AS
SELECT
    s.signalregistry,
    s.telescref,
    t.observstation,
    -- Computed metrics
    calculate_snqi(s.snrratio, s.noisefloordbm) AS snqi,
    calculate_tols(sp.techsigprob, sp.natsrcprob, sp.sigunique, sp.anomscore) AS tols,
    calculate_rpi(sp.techsigprob, sp.biosigprob, sp.sigunique, sp.anomscore, sp.falseposprob) AS rpi,
    calculate_bfr(s.bwhz, s.centerfreqmhz) AS bfr,
    calculate_oqf(
        calculate_aoi(o.atmostransparency, o.humidityrate, o.windspeedms),
        calculate_lif(o.lunardistdeg, o.atmostransparency),
        t.pointaccarc
    ) AS oqf,
    -- Classifications
    CASE
        WHEN calculate_tols(sp.techsigprob, sp.natsrcprob, sp.sigunique, sp.anomscore) < 0.25 THEN 'Low'
        WHEN calculate_tols(sp.techsigprob, sp.natsrcprob, sp.sigunique, sp.anomscore) < 0.75 THEN 'Medium'
        ELSE 'High'
    END AS tols_category,
    (calculate_snqi(s.snrratio, s.noisefloordbm) > 0) AS is_analyzable,
    (calculate_rpi(sp.techsigprob, sp.biosigprob, sp.sigunique, sp.anomscore, sp.falseposprob) > 3.5
     AND sp.techsigprob > 0.8
     AND sp.anomscore > 5) AS is_target_of_opportunity
FROM signals s
JOIN telescopes t ON s.telescref = t.telescregistry
JOIN observatories o ON t.observstation = o.observstation
LEFT JOIN signalprobabilities sp ON s.signalregistry = sp.signalref;


-- =========================================================================
-- 3. Add columns, trigger, and backfill
-- =========================================================================

ALTER TABLE signals ADD COLUMN IF NOT EXISTS auto_snqi NUMERIC;
ALTER TABLE signals ADD COLUMN IF NOT EXISTS analyzable BOOLEAN;

CREATE OR REPLACE FUNCTION trg_set_signal_snqi()
RETURNS TRIGGER AS $$
BEGIN
    NEW.auto_snqi := calculate_snqi(NEW.snrratio, NEW.noisefloordbm);
    NEW.analyzable := (NEW.auto_snqi > 0);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_signal_auto_snqi ON signals;
CREATE TRIGGER trg_signal_auto_snqi
    BEFORE INSERT OR UPDATE ON signals
    FOR EACH ROW
    EXECUTE FUNCTION trg_set_signal_snqi();

-- Backfill existing rows (trigger fires on UPDATE and sets correct values)
UPDATE signals SET
    auto_snqi = calculate_snqi(snrratio, noisefloordbm),
    analyzable = (calculate_snqi(snrratio, noisefloordbm) > 0);
