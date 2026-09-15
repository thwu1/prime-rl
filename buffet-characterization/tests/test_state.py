"""Tests for ONERA OAT15A transonic buffet analysis outputs.

"""
import json
import csv
import os

EXPECTED_ALPHAS = [2.50, 3.00, 3.10, 3.25, 3.50, 3.90]


def _read_csv(path):
    with open(path) as f:
        return list(csv.DictReader(f))


class TestOutputFilesExist:
    REQUIRED = [
        '/app/results/shock_positions.csv',
        '/app/results/section_loads.csv',
        '/app/results/spectral_analysis.csv',
        '/app/results/buffet_onset.json',
        '/app/results/summary.tec',
        '/app/plots/cp_overlay.png',
        '/app/plots/psd_comparison.png',
    ]

    def test_all_files_present(self):
        for path in self.REQUIRED:
            assert os.path.isfile(path), f"Missing: {path}"
            assert os.path.getsize(path) > 0, f"Empty: {path}"


class TestShockPositions:
    def _rows(self):
        return _read_csv('/app/results/shock_positions.csv')

    def test_row_count(self):
        assert len(self._rows()) == 6

    def test_columns_present(self):
        r = self._rows()[0]
        for col in ('alpha', 'x_shock', 'delta_cp'):
            assert col in r, f"Missing column: {col}"

    def test_alphas_present(self):
        got = sorted(float(r['alpha']) for r in self._rows())
        for exp, act in zip(EXPECTED_ALPHAS, got):
            assert abs(exp - act) < 0.05, f"Expected alpha ~{exp}, got {act}"

    def test_shock_in_physical_range(self):
        for r in self._rows():
            xs = float(r['x_shock'])
            assert 0.25 < xs < 0.65, f"Shock x/c={xs} outside physical range"

    def test_pressure_jump_positive(self):
        for r in self._rows():
            dcp = float(r['delta_cp'])
            assert dcp > 0.05, f"Shock pressure jump {dcp} too small or negative"

    def test_shock_forward_trend(self):
        """Shock should move upstream (lower x/c) with increasing alpha."""
        rows = sorted(self._rows(), key=lambda r: float(r['alpha']))
        x_first = float(rows[0]['x_shock'])
        x_last = float(rows[-1]['x_shock'])
        assert x_last < x_first, (
            f"Shock at highest alpha ({x_last:.3f}) should be forward of "
            f"lowest alpha ({x_first:.3f})")


class TestSectionLoads:
    def _rows(self):
        return _read_csv('/app/results/section_loads.csv')

    def test_row_count(self):
        assert len(self._rows()) == 6

    def test_columns_present(self):
        r = self._rows()[0]
        for col in ('alpha', 'cl', 'cm_qc'):
            assert col in r, f"Missing column: {col}"

    def test_cl_range(self):
        for r in self._rows():
            cl = float(r['cl'])
            alpha = float(r['alpha'])
            assert 0.3 < cl < 1.6, f"Cl={cl} at alpha={alpha} unreasonable"

    def test_cl_increases_with_alpha(self):
        rows = sorted(self._rows(), key=lambda r: float(r['alpha']))
        cl_low = float(rows[0]['cl'])
        cl_high = float(rows[-1]['cl'])
        assert cl_high > cl_low, "Cl should increase with angle of attack"

    def test_cm_range(self):
        for r in self._rows():
            cm = float(r['cm_qc'])
            alpha = float(r['alpha'])
            assert -0.5 < cm < 0.15, f"Cm_qc={cm} at alpha={alpha} unreasonable"

    def test_cl_low_alpha_specific(self):
        """At alpha=2.50, Cl should be roughly 0.6-1.1 for OAT15A at M=0.73."""
        rows = sorted(self._rows(), key=lambda r: float(r['alpha']))
        cl = float(rows[0]['cl'])
        assert 0.5 < cl < 1.2, f"Cl={cl} at lowest alpha outside expected range"


class TestSpectralAnalysis:
    def _rows(self):
        return _read_csv('/app/results/spectral_analysis.csv')

    def test_row_count(self):
        assert len(self._rows()) == 6

    def test_columns_present(self):
        r = self._rows()[0]
        for col in ('alpha', 'f_dominant_hz', 'strouhal', 'psd_peak',
                     'narrowband_fraction'):
            assert col in r, f"Missing column: {col}"

    def test_buffet_frequency_at_high_alpha(self):
        """At developed buffet (alpha >= 3.25), dominant freq should be 40-150 Hz."""
        for r in self._rows():
            alpha = float(r['alpha'])
            f_dom = float(r['f_dominant_hz'])
            if alpha >= 3.25:
                assert 40 < f_dom < 150, (
                    f"Buffet freq {f_dom} Hz at alpha={alpha} outside range")

    def test_strouhal_at_high_alpha(self):
        """Strouhal number for OAT15A buffet is ~0.06-0.08."""
        for r in self._rows():
            alpha = float(r['alpha'])
            st = float(r['strouhal'])
            if alpha >= 3.25:
                assert 0.03 < st < 0.15, (
                    f"St={st} at alpha={alpha} outside range")

    def test_narrowband_increases(self):
        """Narrowband fraction should be higher at buffet than pre-buffet."""
        rows = sorted(self._rows(), key=lambda r: float(r['alpha']))
        nb_low = float(rows[0]['narrowband_fraction'])
        nb_high = float(rows[-1]['narrowband_fraction'])
        assert nb_high > nb_low, (
            "Narrowband fraction should increase from pre-buffet to buffet")

    def test_psd_peak_orders_of_magnitude(self):
        """PSD peak at buffet should be orders of magnitude above pre-buffet."""
        rows = sorted(self._rows(), key=lambda r: float(r['alpha']))
        pk_low = float(rows[0]['psd_peak'])
        pk_high = float(rows[-1]['psd_peak'])
        if pk_low > 0:
            assert pk_high / pk_low > 100, (
                "PSD peak should increase by >100x from pre-buffet to buffet")


class TestBuffetOnset:
    def _data(self):
        with open('/app/results/buffet_onset.json') as f:
            return json.load(f)

    def test_onset_range(self):
        d = self._data()
        assert 'onset_alpha_deg' in d, "Missing onset_alpha_deg"
        onset = d['onset_alpha_deg']
        assert 2.8 < onset < 3.4, f"Buffet onset {onset} outside range [2.8, 3.4]"

    def test_classification_count(self):
        d = self._data()
        assert 'classification' in d, "Missing classification"
        assert len(d['classification']) >= 6, (
            f"Expected >= 6 classifications, got {len(d['classification'])}")

    def test_low_alpha_pre_buffet(self):
        c = self._data()['classification']
        for key in c:
            if abs(float(key) - 2.50) < 0.1:
                val = c[key].lower().replace('-', '_').replace(' ', '_')
                assert 'pre' in val, (
                    f"alpha=2.50 should be pre-buffet, got '{c[key]}'")

    def test_high_alpha_buffet(self):
        c = self._data()['classification']
        for key in c:
            if abs(float(key) - 3.90) < 0.1:
                val = c[key].lower()
                assert 'buffet' in val and 'pre' not in val, (
                    f"alpha=3.90 should be buffet, got '{c[key]}'")

    def test_monotonic_classification(self):
        """All pre-buffet angles should be below all buffet angles."""
        d = self._data()
        c = d['classification']
        pre = [float(k) for k, v in c.items()
               if 'pre' in v.lower()]
        buf = [float(k) for k, v in c.items()
               if 'buffet' in v.lower() and 'pre' not in v.lower()]
        if pre and buf:
            assert max(pre) < min(buf), (
                "Classification should be monotonic: all pre-buffet < all buffet")


class TestPlots:
    PNG_MAGIC = b'\x89PNG\r\n\x1a\n'

    def test_cp_plot_valid_png(self):
        with open('/app/plots/cp_overlay.png', 'rb') as f:
            assert f.read(8) == self.PNG_MAGIC, "cp_overlay.png not valid PNG"

    def test_psd_plot_valid_png(self):
        with open('/app/plots/psd_comparison.png', 'rb') as f:
            assert f.read(8) == self.PNG_MAGIC, "psd_comparison.png not valid PNG"

    def test_plots_nontrivial_size(self):
        for p in ['/app/plots/cp_overlay.png', '/app/plots/psd_comparison.png']:
            sz = os.path.getsize(p)
            assert sz > 5000, f"{p} too small ({sz} bytes)"


class TestGnuplotUsed:
    GP_EXTS = ('.gp', '.gnuplot', '.plt', '.gnu')

    def test_gnuplot_scripts_present(self):
        found = [f for f in os.listdir('/app/plots')
                 if any(f.endswith(e) for e in self.GP_EXTS)]
        assert len(found) >= 1, (
            "No gnuplot script files found in /app/plots/")

    def test_gnuplot_script_has_plot_command(self):
        found = [os.path.join('/app/plots', f)
                 for f in os.listdir('/app/plots')
                 if any(f.endswith(e) for e in self.GP_EXTS)]
        for sp in found:
            with open(sp) as fh:
                content = fh.read().lower()
            assert 'set terminal' in content or 'set term' in content, (
                f"{sp}: missing 'set terminal' directive")
            assert 'plot ' in content or 'splot ' in content, (
                f"{sp}: missing plot command")


class TestTecplotSummary:
    def _content(self):
        with open('/app/results/summary.tec') as f:
            return f.read()

    def test_has_variables_header(self):
        assert 'VARIABLES' in self._content().upper()

    def test_has_zone_header(self):
        assert 'ZONE' in self._content().upper()

    def test_required_variable_names(self):
        upper = self._content().upper()
        for var in ['ALPHA', 'CL']:
            assert var in upper, f"Missing variable '{var}' in summary.tec"

    def test_data_line_count(self):
        lines = self._content().strip().split('\n')
        data = [l for l in lines
                if l.strip()
                and not l.strip().upper().startswith(
                    ('TITLE', 'VARIABLES', 'ZONE', '#'))]
        assert len(data) == 6, f"Expected 6 data lines, got {len(data)}"

    def test_data_values_numeric(self):
        lines = self._content().strip().split('\n')
        data = [l for l in lines
                if l.strip()
                and not l.strip().upper().startswith(
                    ('TITLE', 'VARIABLES', 'ZONE', '#'))]
        for line in data:
            vals = line.split()
            assert len(vals) >= 7, f"Expected >= 7 columns, got {len(vals)}"
            for v in vals:
                float(v)  # will raise if non-numeric


class TestPhysicalConsistency:
    def test_shock_and_load_consistency(self):
        """Higher alpha -> higher Cl and more forward shock."""
        shocks = sorted(_read_csv('/app/results/shock_positions.csv'),
                        key=lambda r: float(r['alpha']))
        loads = sorted(_read_csv('/app/results/section_loads.csv'),
                       key=lambda r: float(r['alpha']))

        xs_first = float(shocks[0]['x_shock'])
        xs_last = float(shocks[-1]['x_shock'])
        cl_first = float(loads[0]['cl'])
        cl_last = float(loads[-1]['cl'])

        assert cl_last > cl_first, "Cl must increase with alpha"
        assert xs_last < xs_first, "Shock must move forward with alpha"

    def test_spectral_and_onset_consistency(self):
        """Onset angle should separate low and high spectral energy."""
        with open('/app/results/buffet_onset.json') as f:
            onset_data = json.load(f)
        spectra = sorted(_read_csv('/app/results/spectral_analysis.csv'),
                         key=lambda r: float(r['alpha']))

        onset = onset_data['onset_alpha_deg']
        pre_peaks = [float(r['psd_peak']) for r in spectra
                     if float(r['alpha']) < onset]
        buf_peaks = [float(r['psd_peak']) for r in spectra
                     if float(r['alpha']) >= onset]

        if pre_peaks and buf_peaks:
            assert max(pre_peaks) < max(buf_peaks), (
                "Max PSD peak in pre-buffet should be less than in buffet")
