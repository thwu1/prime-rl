
import ctypes
import math
import os
import sys
from datetime import date
from decimal import Decimal

import numpy as np
import pytest

sys.path.insert(0, '/app')
import tvm


# ---------------------------------------------------------------------------
# Future Value
# ---------------------------------------------------------------------------
class TestFv:
    def test_basic(self):
        result = tvm.fv(0.075, 20, -2000, 0, 0)
        np.testing.assert_allclose(result, 86609.362673042924, rtol=1e-10)

    def test_begin_timing(self):
        result = tvm.fv(0.075, 20, -2000, 0, 1)
        np.testing.assert_allclose(result, 93105.064874, rtol=1e-5)

    def test_zero_rate_array(self):
        result = tvm.fv([0, 0.1], 5, 100, 0)
        np.testing.assert_allclose(result, [-500, -610.51], rtol=1e-4)

    def test_decimal(self):
        result = tvm.fv(Decimal('0.075'), Decimal('20'), Decimal('-2000'),
                        Decimal('0'), Decimal('0'))
        assert isinstance(result, Decimal)
        assert abs(result - Decimal('86609.36267304300040536731624')) < Decimal('1e-10')

    def test_broadcast_2d(self):
        result = tvm.fv([[0.1], [0.2]], 5, 100, 0, [0, 1])
        desired = [[-610.510000, -671.561000], [-744.160000, -892.992000]]
        np.testing.assert_allclose(result, desired, rtol=1e-4)


# ---------------------------------------------------------------------------
# Present Value
# ---------------------------------------------------------------------------
class TestPv:
    def test_basic(self):
        result = tvm.pv(0.07, 20, 12000, 0)
        np.testing.assert_allclose(result, -127128.17, rtol=1e-2)

    def test_decimal(self):
        result = tvm.pv(Decimal('0.07'), Decimal('20'), Decimal('12000'),
                        Decimal('0'))
        assert isinstance(result, Decimal)
        expected = Decimal('-127128.1709461939327295222005')
        assert abs(result - expected) < Decimal('1e-7')


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------
class TestPmt:
    def test_basic(self):
        result = tvm.pmt(0.08 / 12, 5 * 12, 15000)
        np.testing.assert_allclose(result, -304.145914, rtol=1e-6)

    def test_zero_rate(self):
        result = tvm.pmt(0.0, 5 * 12, 15000)
        np.testing.assert_allclose(result, -250.0)

    def test_decimal(self):
        result = tvm.pmt(Decimal('0.08') / Decimal('12'), 5 * 12, 15000)
        assert isinstance(result, Decimal)
        expected = Decimal('-304.1459143262052370338701494')
        assert abs(result - expected) < Decimal('1e-7')

    def test_decimal_zero_rate(self):
        result = tvm.pmt(Decimal('0'), Decimal('60'), Decimal('15000'))
        assert result == -250

    def test_broadcast(self):
        res = tvm.pmt([[0.0, 0.8], [0.3, 0.8]], [12, 3], [2000, 20000])
        expected = np.array([[-166.66667, -19311.258],
                             [-626.90814, -19311.258]])
        np.testing.assert_allclose(res, expected, rtol=1e-4)


# ---------------------------------------------------------------------------
# Number of Periods
# ---------------------------------------------------------------------------
class TestNper:
    def test_basic(self):
        result = tvm.nper([0, 0.075], -2000, 0, 100000)
        np.testing.assert_allclose(result, [50, 21.544944], rtol=1e-5)

    def test_zero_rate(self):
        result = tvm.nper(0, -100, 1000)
        assert result == 10

    def test_infinite_payments(self):
        result = tvm.nper(0, -0.0, 1000)
        assert result == np.inf

    def test_nonzero_pv_fv(self):
        result = tvm.nper(0.1, 0, -500, 1500)
        np.testing.assert_allclose(result, 11.52670461, rtol=1e-5)

    def test_begin_timing(self):
        result = tvm.nper(0.075, -2000, 0, 100000.0, [0, 1])
        np.testing.assert_allclose(result, [21.5449442, 20.76156441], rtol=1e-4)


# ---------------------------------------------------------------------------
# Interest Portion of Payment
# ---------------------------------------------------------------------------
class TestIpmt:
    def test_basic(self):
        result = tvm.ipmt(0.1 / 12, 1, 24, 2000)
        np.testing.assert_allclose(result, -16.666667, rtol=1e-5)

    def test_begin_period1_is_zero(self):
        result = tvm.ipmt(0.1 / 12, 1, 24, 2000, 0, 1)
        assert result == 0

    def test_invalid_per_returns_nan(self):
        result = tvm.ipmt(0.1 / 12, 0, 24, 2000)
        assert np.isnan(result)

    def test_begin_per_gt1(self):
        rate = 0.001988079518355057
        result = tvm.ipmt(rate, 2, 360, 300000, 0, 1)
        np.testing.assert_allclose(result, -594.107158, rtol=1e-5)

    def test_begin_per3(self):
        rate = 0.001988079518355057
        result = tvm.ipmt(rate, 3, 360, 300000, 0, 1)
        np.testing.assert_allclose(result, -592.971592, rtol=1e-5)

    def test_decimal(self):
        result = tvm.ipmt(Decimal('0.1') / Decimal('12'), 1, 24, 2000)
        assert isinstance(result, Decimal)
        assert abs(result - Decimal('-16.66666666666666666666666667')) < Decimal('1e-5')

    def test_broadcasting(self):
        desired = [np.nan, -16.66666667, -16.03647345, -15.40102862, -14.76028842]
        result = tvm.ipmt(0.1 / 12, np.arange(5), 24, 2000)
        np.testing.assert_allclose(result, desired, rtol=1e-5)


# ---------------------------------------------------------------------------
# Principal Portion of Payment
# ---------------------------------------------------------------------------
class TestPpmt:
    def test_basic(self):
        result = tvm.ppmt(0.1 / 12, 1, 60, 55000)
        np.testing.assert_allclose(result, -710.25, rtol=1e-3)

    def test_begin_timing(self):
        result = tvm.ppmt(0.1 / 12, 1, 60, 55000, 0, 1)
        np.testing.assert_allclose(result, -1158.929712, rtol=1e-5)

    def test_pmt_identity_across_schedule(self):
        """pmt = ipmt + ppmt must hold for every period."""
        rate = 0.08 / 12
        nper = 60
        pv = 15000
        total_pmt = tvm.pmt(rate, nper, pv)
        for per in range(1, nper + 1):
            ipmt_val = tvm.ipmt(rate, per, nper, pv)
            ppmt_val = tvm.ppmt(rate, per, nper, pv)
            np.testing.assert_allclose(
                ipmt_val + ppmt_val, total_pmt, rtol=1e-10,
                err_msg=f"identity failed at period {per}")

    def test_decimal(self):
        result = tvm.ppmt(
            Decimal('0.1') / Decimal('12'), Decimal('1'),
            Decimal('60'), Decimal('55000'))
        assert isinstance(result, Decimal)
        assert abs(result - Decimal('-710.2541257864217612489830917')) < Decimal('1e-3')


# ---------------------------------------------------------------------------
# Rate (Newton-Raphson solver)
# ---------------------------------------------------------------------------
class TestRate:
    def test_basic(self):
        result = tvm.rate(10, 0, -3500, 10000)
        np.testing.assert_allclose(result, 0.1107, rtol=1e-3)

    def test_infeasible_returns_nan(self):
        result = tvm.rate(12, 400, 10000, 5000)
        assert np.isnan(result)

    def test_decimal(self):
        result = tvm.rate(Decimal('10'), Decimal('0'),
                          Decimal('-3500'), Decimal('10000'))
        assert isinstance(result, Decimal)
        expected = Decimal('0.1106908537142689284704528100')
        assert abs(result - expected) < Decimal('1e-6')

    def test_vectorised(self):
        nper = 2
        pmt_val = 0
        pv = [-593.06, -4725.38, -662.05, -428.78]
        fv_val = [214.07, 4509.97, 224.11, 686.29]
        expected = [-0.39920185, -0.02305873, -0.41818459, 0.26513414]
        result = tvm.rate(nper, pmt_val, pv, fv_val)
        np.testing.assert_allclose(result, expected, rtol=1e-4)


# ---------------------------------------------------------------------------
# Net Present Value
# ---------------------------------------------------------------------------
class TestNpv:
    def test_basic(self):
        result = tvm.npv(0.05, [-15000, 1500, 2500, 3500, 4500, 6000])
        np.testing.assert_allclose(result, 122.89, rtol=1e-2)

    def test_negative_one_rate_returns_nan(self):
        result = tvm.npv(-1, [0, 1, 2, 3, 4])
        assert np.isnan(result)

    def test_negative_one_int(self):
        result = tvm.npv(-1, list(range(5)))
        assert np.isnan(result)


# ---------------------------------------------------------------------------
# Internal Rate of Return
# ---------------------------------------------------------------------------
class TestIrr:
    @pytest.mark.parametrize("v, desired", [
        ([-150000, 15000, 25000, 35000, 45000, 60000], 0.0524),
        ([-100, 0, 0, 74], -0.0955),
        ([-100, 39, 59, 55, 20], 0.28095),
        ([-100, 100, 0, -7], -0.0833),
        ([-100, 100, 0, 7], 0.06206),
        ([-5, 10.5, 1, -8, 1], 0.0886),
    ])
    def test_basic_values(self, v, desired):
        np.testing.assert_allclose(tvm.irr(v), desired, rtol=1e-2)

    def test_no_solution_positive(self):
        assert np.isnan(tvm.irr([1, 2, 3]))

    def test_no_solution_negative(self):
        assert np.isnan(tvm.irr([-1, -2, -3]))

    def test_npv_irr_congruence(self):
        cashflows = [-40000, 5000, 8000, 12000, 30000]
        r = tvm.irr(cashflows)
        np.testing.assert_allclose(tvm.npv(r, cashflows), 0, atol=1e-8)

    def test_pathological_gh15(self):
        """Cashflows spanning ~300 orders of magnitude must yield finite IRR."""
        v = [
            -3000.0,
            2.3926932267015667e-07,
            4.1672087103345505e-16,
            5.3965110036378706e-25,
            5.1962551071806174e-34,
            3.7202955645436402e-43,
            1.9804961711632469e-52,
            7.8393517651814181e-62,
            2.3072565113911438e-71,
            5.0491839233308912e-81,
            8.2159177668499263e-91,
            9.9403244366963527e-101,
            8.942410813633967e-111,
            5.9816122646481191e-121,
            2.9750309031844241e-131,
            1.1002067043497954e-141,
            3.0252876563518021e-152,
            6.1854121948207909e-163,
            9.4032980015353301e-174,
            1.0629218520017728e-184,
            8.9337141847171845e-196,
            5.5830607698467935e-207,
            2.5943122036622652e-218,
            8.9635842466507006e-230,
            2.3027710094332358e-241,
            4.3987510596745562e-253,
            6.2476630372575209e-265,
            6.598046841695288e-277,
            5.1811095266842017e-289,
            3.0250999925830644e-301,
            1.3133070599585015e-313,
        ]
        result = tvm.irr(v)
        assert np.isfinite(result)
        np.testing.assert_allclose(result, -0.9999999990596069, rtol=1e-9)

    def test_gh39(self):
        cashflows = [
            -217500.0, -217500.0,
            108466.80462450592, 101129.96439328062,
            93793.12416205535, 86456.28393083003,
            79119.44369960476, 71782.60346837944,
            64445.76323715414, 57108.92300592884,
            49772.08277470355, 42435.24254347826,
            35098.40231225296, 27761.56208102766,
            20424.721849802358, 13087.88161857707,
            5751.041387351768, -1585.7988438735192,
            -8922.639075098821, -16259.479306324123,
            -23596.31953754941, -30933.159768774713,
            -38270.0, -45606.8402312253,
            -52943.680462450604, -60280.520693675906,
            -67617.36092490121,
        ]
        np.testing.assert_allclose(tvm.irr(cashflows), 0.12, rtol=1e-2)

    def test_gh44(self):
        cf = [-1678.87, 771.96, 1814.05, 3520.30, 3552.95, 3584.99, 4789.91, -1]
        np.testing.assert_allclose(tvm.irr(cf), 1.00426, rtol=1e-3)

    def test_trailing_zeros(self):
        np.testing.assert_allclose(
            tvm.irr([-5, 10.5, 1, -8, 1, 0, 0, 0]),
            0.0886,
            rtol=1e-2,
        )


# ---------------------------------------------------------------------------
# Modified Internal Rate of Return
# ---------------------------------------------------------------------------
class TestMirr:
    @pytest.mark.parametrize("values, fr, rr, expected", [
        ([-4500, -800, 800, 800, 600, 600, 800, 800, 700, 3000],
         0.08, 0.055, 0.0666),
        ([-120000, 39000, 30000, 21000, 37000, 46000],
         0.10, 0.12, 0.126094),
        ([100, 200, -50, 300, -200], 0.05, 0.06, 0.3428),
    ])
    def test_basic_values(self, values, fr, rr, expected):
        result = tvm.mirr(values, fr, rr)
        decimal_part_len = len(str(expected).split('.')[1])
        tol = 10 ** -decimal_part_len
        np.testing.assert_allclose(result, expected, atol=tol)

    def test_no_solution_all_positive(self):
        result = tvm.mirr([39000, 30000, 21000, 37000, 46000], 0.10, 0.12)
        assert np.isnan(result)

    def test_no_solution_all_negative(self):
        result = tvm.mirr([-100, -50, -60, -70], 0.10, 0.12)
        assert np.isnan(result)


# ---------------------------------------------------------------------------
# Amortization schedule consistency
# ---------------------------------------------------------------------------
class TestAmortizationSchedule:
    def test_30_year_mortgage(self):
        """Full 360-period schedule must close to zero balance."""
        rate = 0.065 / 12
        nper = 360
        pv = 300000
        monthly_pmt = tvm.pmt(rate, nper, pv)

        balance = float(pv)
        total_principal = 0.0

        for per in range(1, nper + 1):
            i = tvm.ipmt(rate, per, nper, pv)
            p = tvm.ppmt(rate, per, nper, pv)
            np.testing.assert_allclose(
                i + p, monthly_pmt, rtol=1e-10,
                err_msg=f"pmt identity failed at period {per}")
            balance += float(p)
            total_principal += float(p)

        np.testing.assert_allclose(balance, 0.0, atol=1e-4)
        np.testing.assert_allclose(-total_principal, pv, rtol=1e-6)


# ---------------------------------------------------------------------------
# Extended NPV (irregular dates)
# ---------------------------------------------------------------------------
class TestXnpv:
    def test_exact_annual_365(self):
        """Exactly 365-day gap should give same result as standard NPV."""
        dates = [date(2019, 1, 1), date(2020, 1, 1)]
        result = tvm.xnpv(0.1, [-1000, 1100], dates)
        # 365/365 = 1.0, so xnpv = -1000 + 1100/1.1 = 0
        np.testing.assert_allclose(result, 0.0, atol=1e-8)

    def test_rate_zero(self):
        """At rate=0, xnpv should equal sum of cashflows."""
        dates = [date(2020, 1, 1), date(2020, 7, 1), date(2021, 1, 1)]
        result = tvm.xnpv(0.0, [-1000, 500, 600], dates)
        np.testing.assert_allclose(result, 100.0, atol=1e-10)

    def test_leap_year_discount(self):
        """366-day gap should produce slightly more discounting than 365."""
        dates = [date(2020, 1, 1), date(2021, 1, 1)]  # 366 days
        result = tvm.xnpv(0.1, [-1000, 1100], dates)
        # More discounting => xnpv < 0
        assert result < 0
        np.testing.assert_allclose(result, -0.261, atol=0.05)

    def test_multi_cashflow(self):
        """Multiple irregular cashflows should sum correctly."""
        dates = [date(2020, 1, 1), date(2020, 4, 1),
                 date(2020, 10, 1), date(2021, 3, 1)]
        cf = [-5000, 1500, 2000, 2500]
        result = tvm.xnpv(0.08, cf, dates)
        # All cashflows are within ~14 months; should be close to sum
        assert result > 0  # total inflows exceed outflow at 8%
        assert result < 1000  # but not by a huge margin


# ---------------------------------------------------------------------------
# Extended IRR (irregular dates)
# ---------------------------------------------------------------------------
class TestXirr:
    def test_exact_annual(self):
        """365-day gap: xirr should match regular IRR exactly."""
        dates = [date(2019, 1, 1), date(2020, 1, 1)]
        result = tvm.xirr([-1000, 1100], dates)
        np.testing.assert_allclose(result, 0.1, rtol=1e-4)

    def test_congruence(self):
        """xnpv(xirr(cf, d), cf, d) should be approximately zero."""
        cf = [-10000, 2750, 4250, 3250, 2750]
        dates = [date(2020, 1, 1), date(2020, 7, 1),
                 date(2021, 1, 1), date(2021, 7, 1),
                 date(2022, 1, 1)]
        r = tvm.xirr(cf, dates)
        assert np.isfinite(r)
        np.testing.assert_allclose(tvm.xnpv(r, cf, dates), 0.0, atol=1e-6)

    def test_no_solution_same_sign(self):
        """All-positive cashflows should return NaN."""
        dates = [date(2020, 1, 1), date(2021, 1, 1), date(2022, 1, 1)]
        result = tvm.xirr([100, 200, 300], dates)
        assert np.isnan(result)

    def test_large_return(self):
        """Quick doubling should give a high xirr."""
        dates = [date(2020, 1, 1), date(2020, 7, 1)]
        result = tvm.xirr([-1000, 2000], dates)
        # Money doubled in ~half a year: very high annual rate
        assert np.isfinite(result)
        assert result > 2.0  # annualised > 200%
        np.testing.assert_allclose(
            tvm.xnpv(result, [-1000, 2000], dates), 0.0, atol=1e-6)


# ---------------------------------------------------------------------------
# Native C Backend
# ---------------------------------------------------------------------------
class TestNativeBackend:
    def test_shared_library_exists(self):
        """The native shared library must be built at the expected path."""
        lib_path = '/app/native/libdiscount.so'
        assert os.path.exists(lib_path), \
            f"Native shared library not found at {lib_path}"

    def test_native_library_loadable(self):
        """The library must be loadable and export npv_native."""
        lib = ctypes.CDLL('/app/native/libdiscount.so')
        assert hasattr(lib, 'npv_native'), \
            "npv_native symbol not found in libdiscount.so"

    def test_native_npv_integration(self):
        """tvm module must successfully load the native backend."""
        assert tvm._npv_native is not None, \
            "tvm._npv_native is None — native backend not loaded"

    def test_native_npv_basic_directly(self):
        """Call npv_native via ctypes directly to verify correctness."""
        lib = ctypes.CDLL('/app/native/libdiscount.so')
        npv_fn = lib.npv_native
        npv_fn.argtypes = [
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        npv_fn.restype = ctypes.c_double

        values = [-15000.0, 1500.0, 2500.0, 3500.0, 4500.0, 6000.0]
        c_vals = (ctypes.c_double * len(values))(*values)
        result = npv_fn(0.05, c_vals, len(values))
        np.testing.assert_allclose(result, 122.89, rtol=1e-2)

    def test_native_npv_rate_neg1(self):
        """Native backend must return NaN for rate == -1."""
        lib = ctypes.CDLL('/app/native/libdiscount.so')
        npv_fn = lib.npv_native
        npv_fn.argtypes = [
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        npv_fn.restype = ctypes.c_double

        values = [0.0, 1.0, 2.0, 3.0, 4.0]
        c_vals = (ctypes.c_double * len(values))(*values)
        result = npv_fn(-1.0, c_vals, len(values))
        assert np.isnan(result), \
            f"Native NPV with rate=-1 should be NaN, got {result}"

    def test_native_npv_zero_rate(self):
        """At rate=0, NPV should equal sum of values."""
        lib = ctypes.CDLL('/app/native/libdiscount.so')
        npv_fn = lib.npv_native
        npv_fn.argtypes = [
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.c_int,
        ]
        npv_fn.restype = ctypes.c_double

        values = [100.0, 200.0, 300.0]
        c_vals = (ctypes.c_double * len(values))(*values)
        result = npv_fn(0.0, c_vals, len(values))
        np.testing.assert_allclose(result, 600.0, rtol=1e-10)

    def test_native_discount_factors_exported(self):
        """The discount_factors symbol must also be exported."""
        lib = ctypes.CDLL('/app/native/libdiscount.so')
        assert hasattr(lib, 'discount_factors'), \
            "discount_factors symbol not found in libdiscount.so"
