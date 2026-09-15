/*----------------------------------------------------------------
  Raven Library Source Code
  Copyright (c) 2008-2023 the Raven Development Team
  ----------------------------------------------------------------*/
#ifndef _DIAGNOSTICS_H
#define _DIAGNOSTICS_H


#include "RavenInclude.h"
#include "TimeSeries.h"

enum diag_type {
  DIAG_NASH_SUTCLIFFE,
  DIAG_DAILY_NSE,
  DIAG_NASH_SUTCLIFFE_DER,
  DIAG_NASH_SUTCLIFFE_RUN,
  DIAG_LOG_NASH,
  DIAG_NSE4,
  DIAG_FUZZY_NASH,
  DIAG_RMSE,
  DIAG_RMSE_DER,
  DIAG_KLING_GUPTA,
  DIAG_KGE_PRIME,
  DIAG_DAILY_KGE,
  DIAG_KLING_GUPTA_DER,
  DIAG_KLING_GUPTA_DEVIATION,
  DIAG_PCT_BIAS,
  DIAG_ABS_PCT_BIAS,
  DIAG_ABSERR,
  DIAG_ABSERR_RUN,
  DIAG_ABSMAX,
  DIAG_PDIFF,
  DIAG_PCT_PDIFF,
  DIAG_ABS_PCT_PDIFF,
  DIAG_TMVOL,
  DIAG_TMVOL_MARE,
  DIAG_RCOEF,
  DIAG_NSC,
  DIAG_RSR,
  DIAG_R2,
  DIAG_MBF,
  DIAG_R4MS4E,
  DIAG_RTRMSE,
  DIAG_RABSERR,
  DIAG_PERSINDEX,
  DIAG_YEARS_OF_RECORD,
  DIAG_SPEARMAN,
  DIAG_UNRECOGNIZED
};

diag_type StringToDiagnostic(string distring);

///////////////////////////////////////////////////////////////////
/// \brief Data abstraction for time series comparison diagnostics
///
/// Key implementation notes:
///   - _width is an integer field used differently by different metrics:
///     * NASH_SUTCLIFFE_RUN/ABSERR_RUN: moving window size in timesteps
///     * FUZZY_NASH: percentage value (integer); converted via _width/100 (integer division!)
///     * All others: unused (set to DOESNT_EXIST = -1)
///   - ALMOST_INF = 1e+32 (used as sentinel for uncomputable metrics)
///   - RAV_BLANK_DATA = -1.2345 (sentinel for missing observations)
///   - getRanks(values, n, ranks): assigns 0-based ordinal ranks to n values
///   - JulianConvert(nn, start_day, start_year, calendar, tt):
///     converts timestep index nn to calendar date (tt.month, tt.year, etc.)
///     For daily timestep: date = start_date + nn days
//
class CDiagnostic
{
private:
  diag_type   _type;
  int         _width;

public:
  CDiagnostic(const diag_type  typ);
  CDiagnostic(const diag_type  typ, const int wid);
  ~CDiagnostic();

  string    GetName() const;
  diag_type GetType() const;

  double CalculateDiagnostic(CTimeSeriesABC  *pTSmod,
                             CTimeSeriesABC  *pTSObs,
                             CTimeSeriesABC  *pTSWeights,
                             const double    &starttime,
                             const double    &endtime,
                             comparison       compare,
                             double           threshold,
                             const optStruct &Options) const;
};

///////////////////////////////////////////////////////////////////
/// \brief Data abstraction for diagnostic period
class CDiagPeriod
{
private:
  string     _name;
  double     _t_start;
  double     _t_end;
  comparison _comp;
  double     _thresh;

public:
  CDiagPeriod(string name, string startdate, string enddate, comparison compare, double thresh, const optStruct &Options);
  ~CDiagPeriod();

  string     GetName()       const;
  double     GetStartTime()  const;
  double     GetEndTime()    const;
  comparison GetComparison() const;
  double     GetThreshold()  const;
};
#endif
