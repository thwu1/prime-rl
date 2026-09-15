/*----------------------------------------------------------------
  Raven Library Source Code
  Copyright (c) 2008-2024 the Raven Development Team, Ayman Khedr, Konhee Lee
  ----------------------------------------------------------------*/

#include "TimeSeriesABC.h"
#include "Diagnostics.h"


/*****************************************************************
Constructor/Destructor
------------------------------------------------------------------
*****************************************************************/
CDiagnostic::CDiagnostic(diag_type typ)
{
  _type =typ;
  _width =DOESNT_EXIST;
}
CDiagnostic::CDiagnostic(diag_type typ, int wid)
{
  _type =typ;
  _width =wid;
}
CDiagnostic::~CDiagnostic(){}

string CDiagnostic::GetName() const
{
  switch (_type)
  {
  case(DIAG_NASH_SUTCLIFFE):    {return "DIAG_NASH_SUTCLIFFE"; }
  case(DIAG_DAILY_NSE):         {return "DIAG_DAILY_NSE"; }
  case(DIAG_FUZZY_NASH):        {return "DIAG_FUZZY_NASH"; }
  case(DIAG_RMSE):              {return "DIAG_RMSE";}
  case(DIAG_PCT_BIAS):          {return "DIAG_PCT_BIAS";}
  case(DIAG_ABS_PCT_BIAS):      {return "DIAG_ABS_PCT_BIAS"; }
  case(DIAG_ABSERR):            {return "DIAG_ABSERR";}
  case(DIAG_ABSERR_RUN):        {return "DIAG_ABSERR_RUN";}
  case(DIAG_ABSMAX):            {return "DIAG_ABSMAX";}
  case(DIAG_PDIFF):             {return "DIAG_PDIFF";}
  case(DIAG_PCT_PDIFF):         {return "DIAG_PCT_PDIFF";}
  case(DIAG_ABS_PCT_PDIFF):     {return "DIAG_ABS_PCT_PDIFF";}
  case(DIAG_TMVOL):             {return "DIAG_TMVOL";}
  case(DIAG_TMVOL_MARE):        {return "DIAG_TMVOL_MARE";}
  case(DIAG_RCOEF):             {return "DIAG_RCOEF"; }
  case(DIAG_NSC):               {return "DIAG_NSC";}
  case(DIAG_RSR):               {return "DIAG_RSR";}
  case(DIAG_R2):                {return "DIAG_R2";}
  case(DIAG_LOG_NASH):          {return "DIAG_LOG_NASH";}
  case(DIAG_KLING_GUPTA):       {return "DIAG_KLING_GUPTA";}
  case(DIAG_KGE_PRIME):         {return "DIAG_KGE_PRIME";}
  case(DIAG_DAILY_KGE):         {return "DIAG_DAILY_KGE";}
  case(DIAG_NASH_SUTCLIFFE_DER):{return "DIAG_NASH_SUTCLIFFE_DER"; }
  case(DIAG_RMSE_DER):          {return "DIAG_RMSE_DER"; }
  case(DIAG_KLING_GUPTA_DER):   {return "DIAG_KLING_GUPTA_DER"; }
  case(DIAG_KLING_GUPTA_DEVIATION):   {return "DIAG_KLING_GUPTA_DEVIATION"; }
  case(DIAG_NASH_SUTCLIFFE_RUN):{return "DIAG_NASH_SUTCLIFFE_RUN"; }
  case(DIAG_MBF):               {return "DIAG_MBF"; }
  case(DIAG_R4MS4E):            {return "DIAG_R4MS4E"; }
  case(DIAG_RTRMSE):            {return "DIAG_RTRMSE"; }
  case(DIAG_RABSERR):           {return "DIAG_RABSERR"; }
  case(DIAG_PERSINDEX):         {return "DIAG_PERSINDEX"; }
  case(DIAG_NSE4):              {return "DIAG_NSE4"; }
  case(DIAG_YEARS_OF_RECORD):   {return "DIAG_YEARS_OF_RECORD";}
  case(DIAG_SPEARMAN):          {return "DIAG_SPEARMAN";}
  default:                      {return "";}
  }
}

diag_type CDiagnostic::GetType() const
{
  return _type;
}

//////////////////////////////////////////////////////////////////
/// \brief Calculates diagnostic metric comparing modeled vs observed time series
/// \details Key constants used throughout:
///   - RAV_BLANK_DATA: sentinel value for missing observations (configurable)
///   - ALMOST_INF: 1e+32, used as return value when metric cannot be computed
///   - DOESNT_EXIST: -1
///
/// Weight computation pipeline:
///   1. Start with external weights (or 1.0 if none)
///   2. Set weight=0 if observed == RAV_BLANK_DATA
///   3. Set weight=0 if modeled == RAV_BLANK_DATA
///   4. Apply threshold filtering based on sorted observation quantiles
///
/// The 'compare' parameter controls threshold filtering:
///   - COMPARE_GREATERTHAN: zero weight for obs < threshold_value
///   - COMPARE_LESSTHAN: zero weight for obs > threshold_value (with -1 index correction)
///   - COMPARE_IS_EQUAL (default/none): no filtering
///
/// \param pTSMod [in] modeled time series
/// \param pTSObs [in] observed time series
/// \param pTSWeights [in] optional weight time series (NULL for uniform weights)
/// \param starttime [in] start of evaluation period (model time)
/// \param endtime [in] end of evaluation period (model time)
/// \param compare [in] comparison type for threshold filtering
/// \param threshold [in] quantile threshold (0.0 to 1.0)
/// \param Options [in] model options (timestep, calendar, etc.)
//
double CDiagnostic::CalculateDiagnostic(CTimeSeriesABC  *pTSMod,
                                        CTimeSeriesABC  *pTSObs,
                                        CTimeSeriesABC  *pTSWeights,
                                        const double    &starttime,
                                        const double    &endtime,
                                        comparison       compare,
                                        double           threshold,
                                        const optStruct &Options) const
{
  int nn;
  double N=0;
  string filename =pTSObs->GetSourceFile();
  double obsval,modval;
  double weight=1;

  int    skip  =0;
  if (!strcmp(pTSObs->GetName().c_str(), "HYDROGRAPH") && (Options.ave_hydrograph == true)){ skip = 1; }
  double dt = Options.timestep;

  int nnstart=pTSObs->GetTimeIndexFromModelTime(starttime)+skip;
  int nnend  =pTSObs->GetTimeIndexFromModelTime(endtime  )+1;

  threshold=max(min(threshold,1.0),0.0);

  // Modify weights for thresholds/blank observation data
  //----------------------------------------------------------
  double *allvals=new double [nnend];
  double thresh_obsval=0;
  int Nobs=0;
  for(nn=nnstart;nn<nnend;nn++)
  {
    obsval=pTSObs->GetSampledValue(nn);
    if (obsval!=RAV_BLANK_DATA){allvals[Nobs]=obsval;Nobs++;  }
  }
  if(Nobs>1) {
    int corr=0;
    if(compare==COMPARE_LESSTHAN) { corr=-1; }
    quickSort(allvals,0,Nobs-1);
    thresh_obsval=allvals[(int)rvn_floor(threshold*Nobs)+corr];
  }
  delete[] allvals;

  double *baseweight=new double [nnend];
  for(nn=nnstart;nn<nnend;nn++)
  {
    baseweight[nn]=1.0;
    if(pTSWeights != NULL) {
      baseweight[nn]=pTSWeights->GetSampledValue(nn);
    }
    obsval=pTSObs->GetSampledValue(nn);
    modval=pTSMod->GetSampledValue(nn);
    if(obsval==RAV_BLANK_DATA) {
      baseweight[nn]=0.0;
    }
    if(modval==RAV_BLANK_DATA) {
      baseweight[nn]=0.0;
    }
    if(compare==COMPARE_GREATERTHAN) {
      if(obsval<thresh_obsval) {baseweight[nn]=0.0;}
    }
    else if(compare==COMPARE_LESSTHAN) {
      if(obsval>thresh_obsval) {baseweight[nn]=0.0;}
    }
  }


  switch (_type)
  {
  case(DIAG_NASH_SUTCLIFFE)://----------------------------------------------------
  {
    double avgobs=0.0;
    N=0;

    for(nn=nnstart;nn<nnend;nn++)
    {
      weight=baseweight[nn];
      obsval =pTSObs->GetSampledValue(nn);
      avgobs+=weight*obsval;
      N     +=weight;
    }
    if(N>0.0) { avgobs/=N; }

    double sum1(0.0),sum2(0.0);
    for(nn=nnstart;nn<nnend;nn++)
    {
      weight=baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      sum1 += weight*pow(obsval - modval,2);
      sum2 += weight*pow(obsval - avgobs,2);
    }

    if(N>0)
    {
      return 1.0 - (sum1 / sum2);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_NASH_SUTCLIFFE_DER)://----------------------------------------------------
  {
    nnend -= 1;
    double obsval2,modval2;
    double avg=0;
    N=0.0;

    for(nn=nnstart;nn<nnend;nn++)
    {
      weight=baseweight[nn+1]*baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      obsval2= pTSObs->GetSampledValue(nn+1);
      avg+= weight*(obsval2-obsval)/dt;
      N  += weight;
    }
    if(N>0.0) {
      avg/=N;
    }
    double sum1(0.0),sum2(0.0);
    for(nn=nnstart;nn<nnend;nn++)
    {
      weight=baseweight[nn+1]*baseweight[nn];
      obsval2 = pTSObs->GetSampledValue(nn+1);
      obsval  = pTSObs->GetSampledValue(nn);
      modval2 = pTSMod->GetSampledValue(nn+1);
      modval  = pTSMod->GetSampledValue(nn);

      sum1 += weight*pow((obsval2-obsval)/dt - (modval2-modval)/dt,2);
      sum2 += weight*pow((obsval2-obsval)/dt - avg,2);
    }

    if(N>0.0)
    {
      return 1.0 - sum1 / sum2;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_NASH_SUTCLIFFE_RUN)://----------------------------------------------------
  {
    if (_width < 2)
    {
      return -ALMOST_INF;
    }
    if (_width * 2 > nnend)
    {
      return -ALMOST_INF;
    }
    nnend    -= _width;
    nnstart  += _width;

    double avg=0;
    N=0;

    for (nn=nnstart;nn<nnend;nn++)
    {
      int front = 0;
      int back = 0;
      double modavg = 0.0;
      double obsavg = 0.0;
      weight =baseweight[nn];
      front = (int)(floor(_width / 2));
      if (_width % 2 == 1) { back = front;  }
      else                 { back = front-1;}

      for (int k = nn - front; k <= nn + back; k++)
      {
        modavg += pTSMod->GetSampledValue(k);
        obsavg += pTSObs->GetSampledValue(k);
        weight *= baseweight[k];
      }

      obsval = obsavg / _width;

      avg+=obsval*weight;
      N  += weight;
    }
    avg/=N;

    double sum1(0.0),sum2(0.0);
    for (nn=nnstart;nn<nnend;nn++)
    {
      int front = 0;
      int back = 0;
      double modavg = 0.0;
      double obsavg = 0.0;
      weight = baseweight[nn];

      front = (int)floor(_width / 2);
      if(_width % 2 == 1) {back = front;}
      else                {back = front - 1;}

      for(int k = nn - front; k <= nn + back; k++)
      {
        modavg += pTSMod->GetSampledValue(k);
        obsavg += pTSObs->GetSampledValue(k);
        weight *= baseweight[k];
      }

      modval = modavg / _width;
      obsval = obsavg / _width;

      sum1 += pow(obsval - modval,2)*weight;
      sum2 += pow(obsval - avg   ,2)*weight;
    }

    if(N>0.0)
    {
      return 1.0 - sum1 / sum2;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_DAILY_NSE)://----------------------------------------------------
  {
    double avgobs=0.0;
    int freq=(int)(rvn_round(1.0/Options.timestep));
    int shift=(int)((Options.julian_start_day-floor(Options.julian_start_day+TIME_CORRECTION))*freq);
    if (nnstart>skip){shift=0;}
    if (freq==1)     {shift=0;}

    double moddaily=0.0;
    double obsdaily=0.0;
    double dailyN  =0.0;
    N=0;

    for(nn=nnstart+shift;nn<nnend;nn++)
    {
      weight = baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      avgobs+=weight*obsval;
      N     +=weight;
    }
    if(N>0.0) { avgobs/=N; }

    double sum1(0.0),sum2(0.0);
    for(nn=nnstart+shift;nn<nnend;nn++)
    {
      weight = baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      obsdaily+=weight*obsval;
      moddaily+=weight*modval;
      dailyN  +=weight;
      if(((nn-(nnstart+shift))%freq)==(freq-1)) {
        if(dailyN>0) {
          obsdaily/=dailyN;
          moddaily/=dailyN;
          sum1 += pow(obsdaily - moddaily,2)*weight;
          sum2 += pow(obsdaily - avgobs  ,2)*weight;
        }
        dailyN=obsdaily=moddaily=0.0;
      }
    }

    if(N>0)
    {
      return 1.0 - (sum1 / sum2);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_FUZZY_NASH)://----------------------------------------------------
  {
    double avgobs=0.0;
    N=0;
    double pct=_width/100; //"width" is actually percentage. If ==0, reverts to NSE
    for(nn=nnstart;nn<nnend;nn++)
    {
      weight=baseweight[nn];
      obsval =pTSObs->GetSampledValue(nn);
      avgobs+=weight*obsval;
      N     +=weight;
    }
    if(N>0.0) { avgobs/=N; }

    double sum1(0.0),sum2(0.0);
    double eps,eps2;
    for(nn=nnstart;nn<nnend;nn++)
    {
      weight=baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      eps = max(modval - obsval * (1.0 + pct), 0.0) + max(obsval*(1.0 - pct)-modval,0.0);
      eps2= max(avgobs - obsval * (1.0 + pct), 0.0) + max(avgobs*(1.0 - pct)-modval,0.0);
      sum1 += weight*pow(eps ,2);
      sum2 += weight*pow(eps2,2);
    }

    if ((N > 0) && (sum2>0))
    {
      return 1.0 - (sum1 / sum2);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_RMSE)://----------------------------------------------------
  {
    double sum=0.0;
    N=0;
    for(nn=nnstart;nn<nnend;nn++)
    {
      weight=baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      sum+=weight*pow(obsval-modval,2);
      N  +=weight;
    }
    if(N>0.0) {
      return sqrt(sum / N);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_RMSE_DER)://----------------------------------------------------
  {
    double sum;
    N=0;
    sum=0;

    for (nn=nnstart;nn<nnend-1;nn++)
    {
      weight =baseweight[nn]*baseweight[nn+1];
      obsval = pTSObs->GetSampledValue(nn+1) - pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn+1) - pTSMod->GetSampledValue(nn);
      obsval /= dt;
      modval /= dt;

      sum+=weight*pow(obsval-modval,2);
      N  +=weight;
    }
    if (N>0.0) {
      return sqrt(sum / N);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_PCT_BIAS)://-------------------------------------------------
  {
    double sum1(0.0),sum2(0.0);
    N=0;
    for (nn=nnstart;nn<nnend;nn++)
    {
      weight =baseweight[nn];
      obsval=pTSObs->GetSampledValue(nn);
      modval=pTSMod->GetSampledValue(nn);

      sum1+=weight*(modval-obsval);
      sum2+=weight*obsval;
      N   +=weight;
    }
    if (N>0.0)
    {
      return 100.0*sum1/sum2;
    }
    else
    {
      return ALMOST_INF;
    }
  }
  case(DIAG_ABS_PCT_BIAS)://-------------------------------------------------
  {
      double sum1(0.0), sum2(0.0);
      N = 0;
      for (nn = nnstart; nn < nnend; nn++)
      {
          weight = baseweight[nn];
          obsval = pTSObs->GetSampledValue(nn);
          modval = pTSMod->GetSampledValue(nn);

          sum1 += weight * (modval - obsval);
          sum2 += weight * obsval;
          N += weight;
      }
      if (N > 0.0)
      {
          return fabs( 100.0 * sum1 / sum2);
      }
      else
      {
          return ALMOST_INF;
      }
  }
  case(DIAG_ABSERR) ://----------------------------------------------------
  {
    double sum=0.0;
    N = 0;

    for (nn = nnstart; nn < nnend; nn++)
    {
      weight =baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      sum += weight*fabs(obsval - modval);
      N   += weight;
    }
    if (N>0.0)
    {
      return sum / N;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_ABSERR_RUN)://----------------------------------------------------
  {
    if (_width < 2)
    {
      return -ALMOST_INF;
    }
    if (_width * 2 > nnend)
    {
      return -ALMOST_INF;
    }
    nnend    -= _width;
    nnstart  += _width;

    N=0;

    double sum1(0.0);
    for (nn=nnstart;nn<nnend;nn++)
    {
      int front = 0;
      int back = 0;
      double modavg = 0.0;
      double obsavg = 0.0;
      weight = baseweight[nn];

      front = (int)floor(_width / 2);
      if(_width % 2 == 1) {back = front;}
      else                {back = front - 1;}

      for(int k = nn - front; k <= nn + back; k++)
      {
        modavg += pTSMod->GetSampledValue(k);
        obsavg += pTSObs->GetSampledValue(k);
        weight *= baseweight[k];
      }
      N  += weight;

      modval = modavg / _width;
      obsval = obsavg / _width;

      sum1 += fabs(obsval - modval)*weight;
    }

    if(N>0.0)
    {
      return sum1;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_ABSMAX)://----------------------------------------------------
  {
    double maxerr = -ALMOST_INF;
    N=0.0;

    for(nn = nnstart; nn<nnend; nn++)
    {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      if(weight > 0.0) {
        if(fabs(obsval - modval) > maxerr) {
          maxerr = fabs(obsval - modval);
        }
        N+=weight;
      }
    }
    if(N>0.0)
    {
      return maxerr;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_PDIFF) ://----------------------------------------------------
  {
    double maxObs = 0;
    double maxMod = 0;
    N=0;

    for (nn = nnstart; nn<nnend; nn++)
    {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      if (weight> 0) {
        if (obsval > maxObs) {maxObs = obsval;}
        if (modval > maxMod) {maxMod = modval;}
        N+=weight;
      }
    }
    if (N>0.0)
    {
      return maxMod - maxObs;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_PCT_PDIFF)://----------------------------------------------------
  {
      double maxObs = 0;
      double maxMod = 0;
      N = 0;

      for (nn = nnstart; nn < nnend; nn++)
      {
          obsval = pTSObs->GetSampledValue(nn);
          modval = pTSMod->GetSampledValue(nn);
          weight = baseweight[nn];

          if (weight > 0) {
              if (obsval > maxObs) { maxObs = obsval; }
              if (modval > maxMod) { maxMod = modval; }
              N += weight;
          }
      }
      if (N > 0.0)
      {
          return (100.0 * ((maxMod - maxObs)/maxObs));
      }
      else
      {
          return -ALMOST_INF;
      }
  }
  case(DIAG_ABS_PCT_PDIFF)://----------------------------------------------------
  {
      double maxObs = 0;
      double maxMod = 0;
      N = 0;

      for (nn = nnstart; nn < nnend; nn++)
      {
          obsval = pTSObs->GetSampledValue(nn);
          modval = pTSMod->GetSampledValue(nn);
          weight = baseweight[nn];

          if (weight > 0) {
              if (obsval > maxObs) { maxObs = obsval; }
              if (modval > maxMod) { maxMod = modval; }
              N += weight;
          }
      }
      if (N > 0.0)
      {
          return abs(100.0*(maxMod - maxObs) / maxObs);
      }
      else
      {
          return -ALMOST_INF;
      }
  }
  case(DIAG_TMVOL) ://----------------------------------------------------
  {
    int    mon     = 1;
    double n_days  = 0;
    double tmvol   = 0;
    double tempsum = 0;
    time_struct tt;

    // Find month of first valid entry
    for (nn = nnstart; nn < nnend; nn++)
    {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      if (weight != 0)
      {
        JulianConvert(nn, Options.julian_start_day, Options.julian_start_year, Options.calendar, tt);
        mon = tt.month;
        break;
      }
    }

    // Perform diagnostics
    for (nn = nnstart; nn < nnend; nn++)
    {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      if (weight != 0)
      {
        JulianConvert(nn, Options.julian_start_day, Options.julian_start_year, Options.calendar, tt);
        if (tt.month != mon)
        {
          mon = tt.month;
          if (n_days > 0){tmvol += pow((tempsum / n_days), 2);}
          n_days =0;
          tempsum=0.0;
        }
        tempsum += (modval - obsval)*weight;
        n_days  += weight;
      }
      N+=weight;
    }
    // Add up the final month
    if (n_days > 0){tmvol += pow(tempsum / n_days, 2);}

    if (N>0)
    {
      return tmvol;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case (DIAG_TMVOL_MARE):
  {
    int mon = 1;
    double tmvol_abs = 0.0;
    double tempsum = 0.0;
    double obs_sum = 0.0;
    int m_count = 0;
    time_struct tt;

    for (nn = nnstart; nn < nnend; nn++) {
      if (baseweight[nn] != 0) {
        JulianConvert(nn, Options.julian_start_day, Options.julian_start_year,
                      Options.calendar, tt);
        mon = tt.month;
        break;
      }
    }

    for (nn = nnstart; nn < nnend; nn++) {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight = baseweight[nn];

      if (weight != 0) {
        JulianConvert(nn, Options.julian_start_day, Options.julian_start_year,
                      Options.calendar, tt);

        if (tt.month != mon) {
          if (obs_sum > 0) {
            tmvol_abs += fabs(tempsum / obs_sum) * 100.0;
            m_count++;
          }

          mon = tt.month;
          tempsum = 0.0;
          obs_sum = 0.0;
        }

        tempsum += (modval - obsval) * weight;
        obs_sum += obsval * weight;
      }
      N += weight;
    }

    if (obs_sum > 0) {
      tmvol_abs += fabs(tempsum / obs_sum) * 100.0;
      m_count++;
    }

    if (m_count > 0) {
      return tmvol_abs / (double)m_count;
    } else {
      return -ALMOST_INF;
    }
  }
  case(DIAG_RCOEF) ://----------------------------------------------------
  {
    N=0;
    double ModSum = 0;
    double ObsSum = 0;
    double TopSum = 0;
    double nxtobsval,nxtmodval;
    for (nn = nnstart; nn < nnend - 1; nn++)
    {
      nxtobsval = pTSObs->GetSampledValue(nn + 1);
      nxtmodval = pTSMod->GetSampledValue(nn + 1);
      obsval    = pTSObs->GetSampledValue(nn);
      modval    = pTSMod->GetSampledValue(nn);

      weight =baseweight[nn]*baseweight[nn+1];

      ModSum += weight*modval;
      ObsSum += weight*obsval;
      N+=weight;
    }

    double ModAvg = ModSum / N;
    double ObsAvg = ObsSum / N;
    double ModDiffSum = 0;
    double ObsDiffSum = 0;

    for (nn = nnstart; nn < nnend - 1; nn++)
    {
      nxtobsval = pTSObs->GetSampledValue(nn + 1);
      nxtmodval = pTSMod->GetSampledValue(nn + 1);
      obsval    = pTSObs->GetSampledValue(nn);
      modval    = pTSMod->GetSampledValue(nn);

      weight =baseweight[nn]*baseweight[nn+1];

      TopSum += weight*(nxtmodval - nxtobsval) * (modval - obsval);
      ModDiffSum += weight*pow((modval - ModAvg), 2);
      ObsDiffSum += weight*pow((obsval - ObsAvg), 2);
    }

    double modstd = sqrt((ModDiffSum / N));
    double obsstd = sqrt((ObsDiffSum / N));

    if ((N>0) && (obsstd!=0) && (modstd!=0.0))
    {
      return TopSum / N / ((modstd)* (obsstd));
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_NSC) ://----------------------------------------------------
  {
    double nxtobsval,nxtmodval;
    double nsc = 0;
    N=0;
    for (nn = nnstart; nn < nnend - 1; nn++)
    {
      nxtobsval = pTSObs->GetSampledValue(nn + 1);
      nxtmodval = pTSMod->GetSampledValue(nn + 1);
      obsval    = pTSObs->GetSampledValue(nn);
      modval    = pTSMod->GetSampledValue(nn);

      weight =baseweight[nn]*baseweight[nn+1];

      if (weight>0.0)
      {
        if ((ceil((obsval - modval)*1000)/1000)*(ceil((nxtobsval - nxtmodval)*1000)/1000) < 0)
        {
          nsc++;
        }
      }
      N+=weight;
    }

    if (N>0.0)
    {
      return nsc;
    }
    else
    {
      return ALMOST_INF;
    }
  }
  case(DIAG_RSR) ://----------------------------------------------------
  {
    double ObsSum = 0;
    for (nn = nnstart; nn < nnend; nn++)
    {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      ObsSum += obsval*weight;
      N+=weight;
    }

    double ObsAvg = ObsSum / N;
    double TopSum = 0;
    double BotSum = 0;
    for (nn = nnstart; nn < nnend; nn++)
    {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      TopSum += pow((obsval - modval),2)*weight;
      BotSum += pow((obsval - ObsAvg),2)*weight;
    }
    if ((N>0) && (BotSum!=0.0) && (ObsSum!=0.0))
    {
      return sqrt(TopSum/BotSum);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_R2) ://----------------------------------------------------
  {
    double ObsSum = 0;
    double ModSum = 0;

    double CovXY = 0;
    double CovXX = 0;
    double CovYY = 0;

    for (nn = nnstart; nn < nnend; nn++)
    {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      ObsSum += obsval*weight;
      ModSum += modval*weight;
      N+=weight;
    }

    double ObsAvg = ObsSum / N;
    double ModAvg = ModSum / N;

    for (nn = nnstart; nn < nnend; nn++)
    {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      CovXY += weight*(modval-ModAvg)*(obsval-ObsAvg);
      CovXX += weight*(modval-ModAvg)*(modval-ModAvg);
      CovYY += weight*(obsval-ObsAvg)*(obsval-ObsAvg);
    }

    CovXY /= N;
    CovXX /= N;
    CovYY /= N;

    if ((N>0) && (CovXX!=0.0) && (CovYY!=0))
    {
      return pow(CovXY,2)/(CovXX*CovYY);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_LOG_NASH)://-----------------------------------------
  {
    double avg=0;
    N=0;
    for (nn=nnstart;nn<nnend;nn++)
    {
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      if ((obsval <= 0.0) || (obsval==RAV_BLANK_DATA)){obsval=RAV_BLANK_DATA;}
      else                                            {obsval=log(obsval);   }
      if ((modval <= 0.0) || (obsval==RAV_BLANK_DATA)){modval=RAV_BLANK_DATA;}
      else                                            {modval=log(modval);   }

      if (obsval==RAV_BLANK_DATA){weight=0.0;}
      if (modval==RAV_BLANK_DATA){weight=0.0;}
      avg+=obsval*weight;
      N+= weight;
    }
    avg/=N;

    double sum1(0.0),sum2(0.0);
    for (nn=nnstart;nn<nnend;nn++)
    {
      obsval=pTSObs->GetSampledValue(nn);
      modval=pTSMod->GetSampledValue(nn);
      weight =baseweight[nn];

      if ((obsval <= 0.0) || (obsval==RAV_BLANK_DATA)){obsval=RAV_BLANK_DATA;}
      else                                            {obsval=log(obsval);   }
      if ((modval <= 0.0) || (obsval==RAV_BLANK_DATA)){modval=RAV_BLANK_DATA;}
      else                                            {modval=log(modval);   }

      if (obsval==RAV_BLANK_DATA){weight=0.0;}
      if (modval==RAV_BLANK_DATA){weight=0.0;}
      sum1+=pow(obsval-modval,2)*weight;
      sum2+=pow(obsval-avg   ,2)*weight;
    }
    if ((N>0) && (sum2!=0.0))
    {
      return 1.0 - sum1 / sum2;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_KLING_GUPTA)://-----------------------------------------
  case(DIAG_KGE_PRIME)://-------------------------------------------
  case(DIAG_KLING_GUPTA_DEVIATION)://-------------------------------
  {
    double ObsAvg = 0;
    double ModAvg = 0;
    double ObsSum = 0;
    double ModSum = 0;
    double ObsStd = 0;
    double ModStd = 0;
    double Cov = 0;
    N = 0;
    for (nn = nnstart; nn < nnend; nn++)
    {
      weight =baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      ObsSum += obsval*weight;
      ModSum += modval*weight;
      N += weight;
    }
    ObsAvg = ObsSum / N;
    ModAvg = ModSum / N;

    for (nn = nnstart; nn < nnend; nn++)
    {
      weight =baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      ObsStd += pow((obsval - ObsAvg), 2)*weight;
      ModStd += pow((modval - ModAvg), 2)*weight;
      Cov += (obsval - ObsAvg) * (modval - ModAvg)*weight;
    }

    ObsStd = sqrt(ObsStd / N);
    ModStd = sqrt(ModStd / N);
    Cov /= N;

    double r     = Cov / ObsStd / ModStd;
    double Beta  = ModAvg / ObsAvg;
    double Alpha = ModStd / ObsStd;

    if (_type==DIAG_KLING_GUPTA_DEVIATION){Beta=1.0;}

    if (_type==DIAG_KGE_PRIME){if (Beta!=0.0){Alpha/=Beta;}}

    if ((N>0) && ((ObsAvg!=0.0) || (Beta==1.0)) && (ObsStd!=0.0) && (ModStd!=0.0))
    {
      return 1.0 - sqrt(pow((r - 1), 2) + pow((Alpha - 1), 2) + pow((Beta - 1), 2));
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_KLING_GUPTA_DER)://-----------------------------------------
  {
    nnend -= 1;
    double ObsAvg = 0;
    double ModAvg = 0;
    double ObsSum = 0;
    double ModSum = 0;
    double ObsStd = 0;
    double ModStd = 0;
    double Cov = 0;
    N = 0;
    for (nn = nnstart; nn < nnend; nn++)
    {
      weight =baseweight[nn]*baseweight[nn+1];
      obsval = (pTSObs->GetSampledValue(nn + 1) - pTSObs->GetSampledValue(nn))/dt;
      modval = (pTSMod->GetSampledValue(nn + 1) - pTSMod->GetSampledValue(nn))/dt;

      ObsSum += obsval*weight;
      ModSum += modval*weight;
      N += weight;
    }
    ObsAvg = ObsSum / N;
    ModAvg = ModSum / N;

    for (nn = nnstart; nn < nnend; nn++)
    {
      weight =baseweight[nn]*baseweight[nn+1];
      obsval = (pTSObs->GetSampledValue(nn + 1) - pTSObs->GetSampledValue(nn))/dt;
      modval = (pTSMod->GetSampledValue(nn + 1) - pTSMod->GetSampledValue(nn))/dt;

      ObsStd += pow((obsval - ObsAvg), 2)*weight;
      ModStd += pow((modval - ModAvg), 2)*weight;
      Cov += (obsval - ObsAvg) * (modval - ModAvg)*weight;
    }

    ObsStd = sqrt(ObsStd / N);
    ModStd = sqrt(ModStd / N);
    Cov /= N;

    double r = Cov / ObsStd / ModStd;
    double Beta = ModAvg / ObsAvg;
    double Alpha = ModStd / ObsStd;

    if ((N>0) && (ObsAvg!=0.0) && (ObsStd!=0.0) && (ModStd!=0.0))
    {
      return 1.0 - sqrt(pow((r - 1), 2) + pow((Alpha - 1), 2) + pow((Beta - 1), 2));
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_DAILY_KGE)://----------------------------------------------------
  {
    int freq=(int)(rvn_round(1.0/Options.timestep));
    int shift=(int)((Options.julian_start_day-floor(Options.julian_start_day+TIME_CORRECTION))*freq);
    if (nnstart>skip){shift=0;}
    if (freq==1)     {shift=0;}

    double moddaily(0.0), obsdaily(0.0);
    double avgobs  (0.0), avgmod  (0.0);
    double obsstd  (0.0), modstd  (0.0);
    double covar   =0.0;
    double dailyN  =0.0;
    N=0;

    for(nn=nnstart+shift;nn<nnend;nn++)
    {
      weight=baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      avgobs+=weight*obsval;
      avgmod+=weight*modval;
      N     +=weight;
    }
    if(N>0.0) { avgobs/=N; avgmod/=N;}

    for(nn=nnstart+shift;nn<nnend;nn++)
    {
      weight=baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      obsdaily+=weight*obsval;
      moddaily+=weight*modval;
      dailyN  +=weight;

      if(((nn-(nnstart+shift))%freq)==(freq-1)) {
        if(dailyN>0) {
          obsdaily/=dailyN;
          moddaily/=dailyN;
          obsstd+=weight*(obsdaily - avgobs)*(obsdaily - avgobs);
          modstd+=weight*(moddaily - avgmod)*(moddaily - avgmod);
          covar +=weight*(obsdaily - avgobs)*(moddaily - avgmod);
        }
        dailyN=obsdaily=moddaily=0.0;
      }
    }
    if(N>0.0) {
      obsstd = sqrt(obsstd / N);
      modstd = sqrt(modstd / N);
      covar /= N;
    }
    double r     = covar / obsstd / modstd;
    double beta  = avgmod / avgobs;
    double alpha = modstd / obsstd;

    if ((N>0) && (avgobs!=0.0)  && (obsstd!=0.0) && (modstd!=0.0))
    {
      return 1.0 - sqrt(pow((r - 1), 2) + pow((alpha - 1), 2) + pow((beta - 1), 2));
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_MBF)://----------------------------------------------------
  {
    double sum=0.0;
    N = 0;
    for(nn = nnstart; nn < nnend; nn++)
    {
      weight = baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      sum += weight / (1.0 + pow(((modval-obsval) / (2.0*obsval)),2));
      N   +=weight;
    }

    if(N>0)
    {
      return sum;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_R4MS4E)://----------------------------------------------------
  {
    double sum=0.0;
    N=0;
    for(nn=nnstart;nn<nnend;nn++)
    {
      weight = baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      sum+=weight*pow(obsval-modval,4);
      N  +=weight;
    }
    if(N>0.0) {
      return pow( (sum/N), 0.25);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_RTRMSE)://----------------------------------------------------
  {
    double sum=0.0;
    N=0;
    for(nn=nnstart;nn<nnend;nn++)
    {
      weight = baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      sum+=weight*pow( sqrt(obsval)-sqrt(modval), 2);
      N  +=weight;
    }
    if(N>0.0) {
      return sqrt(sum / N);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_RABSERR) ://----------------------------------------------------
  {
    double avgobs=0.0;
    double sum1(0.0),sum2(0.0);
    N=0;

    for(nn=nnstart;nn<nnend;nn++)
    {
      weight = baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      avgobs+=weight*obsval;
      N     +=weight;
    }
    if(N>0.0) { avgobs/=N; }

    for (nn = nnstart; nn < nnend; nn++)
    {
      weight = baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      sum1 += weight*fabs(obsval - modval);
      sum2 += weight*fabs(avgobs - modval);

    }
    if (N>0.0)
    {
      return (sum1 / sum2);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_PERSINDEX)://----------------------------------------------------
  {
    double sum1(0.0),sum2(0.0);
    double prvmodval;
    N=0;
    for(nn=nnstart+1; nn<nnend; nn++)
    {
      prvmodval = pTSMod->GetSampledValue(nn - 1);
      obsval    = pTSObs->GetSampledValue(nn);
      modval    = pTSMod->GetSampledValue(nn);
      weight     =baseweight[nn]*baseweight[nn-1];

      sum1 += weight*(pow( modval-   obsval, 2));
      sum2 += weight*(pow( modval-prvmodval, 2));
      N    += weight;
    }

    if ((N>0.0) && (sum2!=0.0))
    {
      return 1 - (sum1 / sum2);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case(DIAG_YEARS_OF_RECORD):
  {
    for(nn=nnstart;nn<nnend;nn++)
    {
      weight =baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      if (weight>0.0){weight=1.0;}
      N     +=weight;
    }
    return N/365/Options.timestep;
  }
  case(DIAG_NSE4)://----------------------------------------------------
  {
    double avgobs=0.0;
    N=0;

    for(nn=nnstart;nn<nnend;nn++)
    {
      weight = baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      avgobs+=weight*obsval;
      N     +=weight;
    }
    if(N>0.0) { avgobs/=N; }

    double sum1(0.0),sum2(0.0);
    for(nn=nnstart;nn<nnend;nn++)
    {
      weight = baseweight[nn];
      obsval = pTSObs->GetSampledValue(nn);
      modval = pTSMod->GetSampledValue(nn);

      sum1 += weight*pow(obsval - modval,4);
      sum2 += weight*pow(obsval - avgobs,4);
    }

    if(N>0)
    {
      return 1.0 - (sum1 / sum2);
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  case (DIAG_SPEARMAN)://----------------------------------------
  {
    double spearman;
    double *mvals = new double [nnend-nnstart];
    double *ovals = new double [nnend-nnstart];
    int    *rank1 = new int    [nnend-nnstart];
    int    *rank2 = new int    [nnend-nnstart];
    N=0;
    for(nn=nnstart;nn<nnend;nn++)
    {
      obsval=pTSObs->GetSampledValue(nn);
      modval=pTSMod->GetSampledValue(nn);

      if ((obsval!=RAV_BLANK_DATA) && (baseweight[nn]>0.0)){
        ovals[(int)(N)]=obsval;
        mvals[(int)(N)]=modval;
        N++;
      }
    }
    if(N>1) {
      getRanks(mvals,(int)(N),rank1);
      getRanks(ovals,(int)(N),rank2);

      double cov=0;
      double mean1=0;
      double mean2=0;
      double std1=0;
      double std2=0;
      for (int n = 0; n < N; n++) {
        mean1 += rank1[n]/N;
        mean2 += rank2[n]/N;
      }
      for (int n = 0; n < N; n++) {
        std1 += (rank1[n]-mean1)*(rank1[n]-mean1)/N;
        std2 += (rank2[n]-mean2)*(rank2[n]-mean2)/N;
        cov  += (rank1[n]-mean1)*(rank2[n]-mean2)/N;
      }
      spearman = cov / sqrt(std1) / sqrt(std2);
    }
    else
    {
      spearman=0;
    }

    delete[] rank1;
    delete[] rank2;
    delete[] mvals;
    delete[] ovals;
    if(N>0)
    {
      return spearman;
    }
    else
    {
      return -ALMOST_INF;
    }
  }
  default:
  {
    return 0.0;
  }
  }//end switch

  delete [] baseweight; //\todo: fix! This never gets called!!
  return 0;
}

/*****************************************************************
CDiagPeriod
------------------------------------------------------------------
*****************************************************************/
CDiagPeriod::CDiagPeriod(string name,string startdate,string enddate,comparison compare,double thresh,const optStruct &Options)
{
  _name=name;
  _comp=compare;
  _thresh=thresh;

  time_struct tt;
  tt=DateStringToTimeStruct(startdate,"00:00:00",Options.calendar);
  _t_start = TimeDifference(Options.julian_start_day,Options.julian_start_year,tt.julian_day,tt.year,Options.calendar);

  tt=DateStringToTimeStruct(enddate  ,"00:00:00",Options.calendar);
  _t_end   = TimeDifference(Options.julian_start_day,Options.julian_start_year,tt.julian_day,tt.year,Options.calendar);

  if (_t_end<=_t_start){
    string warn;
    warn="CDiagPeriod: :EvaluationPeriod "+_name+": startdate after enddate.";
  }

  _t_start = max(min(_t_start,Options.duration),0.0);
  _t_end   = max(min(_t_end  ,Options.duration),0.0);
}
CDiagPeriod::~CDiagPeriod() {}

string     CDiagPeriod::GetName()      const { return _name;}
double     CDiagPeriod::GetStartTime() const { return _t_start;}
double     CDiagPeriod::GetEndTime()   const { return _t_end;}
comparison CDiagPeriod::GetComparison()const { return _comp; }
double     CDiagPeriod::GetThreshold() const { return _thresh; }

diag_type StringToDiagnostic(string distring)
{
  if      (!distring.compare("NASH_SUTCLIFFE"       )){return DIAG_NASH_SUTCLIFFE;}
  else if (!distring.compare("DAILY_NSE"            )){return DIAG_DAILY_NSE; }
  else if (!distring.compare("RMSE"                 )){return DIAG_RMSE;}
  else if (!distring.compare("PCT_BIAS"             )){return DIAG_PCT_BIAS;}
  else if (!distring.compare("ABS_PCT_BIAS"         )){return DIAG_ABS_PCT_BIAS; }
  else if (!distring.compare("ABSERR"               )){return DIAG_ABSERR;}
  else if (!distring.compare("ABSERR_RUN"           )){return DIAG_ABSERR_RUN;}
  else if (!distring.compare("ABSMAX"               )){return DIAG_ABSMAX;}
  else if (!distring.compare("PDIFF"                )){return DIAG_PDIFF;}
  else if (!distring.compare("PCT_PDIFF"            )){return DIAG_PCT_PDIFF;}
  else if (!distring.compare("ABS_PCT_PDIFF"        )){return DIAG_ABS_PCT_PDIFF;}
  else if (!distring.compare("TMVOL"                )){return DIAG_TMVOL;}
  else if (!distring.compare("TMVOL_MARE"           )){return DIAG_TMVOL_MARE;}
  else if (!distring.compare("RCOEF"                )){return DIAG_RCOEF;}
  else if (!distring.compare("NSC"                  )){return DIAG_NSC;}
  else if (!distring.compare("RSR"                  )){return DIAG_RSR;}
  else if (!distring.compare("R2"                   )){return DIAG_R2;}
  else if (!distring.compare("LOG_NASH"             )){return DIAG_LOG_NASH;}
  else if (!distring.compare("KLING_GUPTA"          )){return DIAG_KLING_GUPTA;}
  else if (!distring.compare("KGE_PRIME"            )){return DIAG_KGE_PRIME;}
  else if (!distring.compare("DAILY_KGE"            )){return DIAG_DAILY_KGE;}
  else if (!distring.compare("NASH_SUTCLIFFE_DER"   )){return DIAG_NASH_SUTCLIFFE_DER;}
  else if (!distring.compare("RMSE_DER"             )){return DIAG_RMSE_DER;}
  else if (!distring.compare("KLING_GUPTA_DER"      )){return DIAG_KLING_GUPTA_DER;}
  else if (!distring.compare("KLING_GUPTA_DEVIATION")){return DIAG_KLING_GUPTA_DEVIATION;}
  else if (!distring.compare("MBF"                  )){return DIAG_MBF;}
  else if (!distring.compare("R4MS4E"               )){return DIAG_R4MS4E;}
  else if (!distring.compare("RTRMSE"               )){return DIAG_RTRMSE;}
  else if (!distring.compare("RABSERR"              )){return DIAG_RABSERR;}
  else if (!distring.compare("PERSINDEX"            )){return DIAG_PERSINDEX;}
  else if (!distring.compare("NSE4"                 )){return DIAG_NSE4;}
  else if (!distring.compare("YEARS_OF_RECORD"      )){return DIAG_YEARS_OF_RECORD; }
  else if (!distring.compare("SPEARMAN"             )){return DIAG_SPEARMAN; }
  else if (!distring.compare("NASH_SUTCLIFFE_RUN"   )){return DIAG_NASH_SUTCLIFFE_RUN; }
  else if (!distring.compare("FUZZY_NASH"           )){return DIAG_FUZZY_NASH; }
  else                                                {return DIAG_UNRECOGNIZED;}
}
