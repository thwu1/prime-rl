# Here are the tests belonging to e3sm suites. Format is
# <test>.<grid>.<compset>[.<testmod>]
#
# suite_name : {
#     "inherit" : (suite1, suite2, ...), # Optional. Suites to inherit tests from. Default is None. Tuple, list, or str.
#     "time"    : "HH:MM:SS",            # Optional. Recommended upper-limit on test time.
#     "share"   : True|False,            # Optional. If True, all tests in this suite share a build. Default is False.
#     "tests"   : (test1, test2, ...)    # Optional. The list of tests for this suite. See above for format. Tuple, list, or str.
# }

_TESTS = {

    "e3sm_mosart_developer" : {
        "share" : True,
        "time"  : "0:45:00",
        "inherit" : ("e3sm_mosart_sediment"),
        "tests" : (
            "ERS.r05_r05.RMOSGPCC.mosart-gpcc_1972",
            "ERS.MOS_USRDAT.RMOSGPCC.mosart-mos_usrdat",
            "SMS.MOS_USRDAT.RMOSGPCC.mosart-unstructure",
            "ERS.r05_r05.RMOSGPCC.mosart-heat",
            )
        },

    "e3sm_mosart_sediment" : {
        "time"  : "0:45:00",
        "tests" : (
            "ERS.MOS_USRDAT.RMOSNLDAS.mosart-sediment",
            )
        },

    "e3sm_land_exeshare" : {
        "share" : True,
        "time"  : "0:45:00",
        "tests" : (
            "ERS.f09_g16.IELMBC",
            "ERS.f19_g16.I1850CNECACNTBC.elm-eca",
            "ERS.f19_g16.I1850CNECACTCBC.elm-eca",
            "ERS.f19_g16.I1850CNRDCTCBC.elm-rd",
            "ERS.f09_g16.I1850GSWCNPRDCTCBC.elm-vstrd",
            "ERS.f19_g16.I1850GSWCNPECACNTBC.elm-eca_f19_g16_I1850GSWCNPECACNTBC",
            "ERS.f19_g16.I20TRGSWCNPECACNTBC.elm-eca_f19_g16_I20TRGSWCNPECACNTBC",
            "ERS.f19_g16.I20TRGSWCNPRDCTCBC.elm-ctc_f19_g16_I20TRGSWCNPRDCTCBC",
            "SMS_Ly2_P1x1.1x1_smallvilleIA.I20TRGSWCNPCROP.elm-lulcc_sville",
            "ERS.r05_r05.ICNPRDCTCBC.elm-cbudget",
            "ERS_Ld150.ELM_USRDAT.I1850CNPRDCTCBC.elm-snowveg_arctic",
            "ERS.ELM_USRDAT.I1850CNPRDCTCBC.elm-usrpft_default_I1850CNPRDCTCBC",
            "ERS.ELM_USRDAT.I1850CNPRDCTCBC.elm-usrpft_codetest_I1850CNPRDCTCBC",
            "ERS.1x1_icycape.I1850GSWCNPRDCTCBC.elm-polygonal_tundra",
            "SMS_Ly1.ELM_USRDAT.I1850CNPRDCTCBC.elm-kilocraft",
            )
        },

    "e3sm_land_exenoshare" : {
        "time"  : "0:45:00",
        "tests" : (
            "ERS.f19_g16.IERA5ELM",
            "ERS.f19_g16.IERA56HRELM",
            "ERS_Ld20.f45_f45.IELMFATES.elm-fates",
            "ERS.f09_g16.IELMBC.elm-simple_decomp",
            "ERS.hcru_hcru.IELM.elm-multi_inst",
            "SMS.ELM_USRDAT.GTSM2ELM.elm-lnd_docn_1way",
            )
        },

    "e3sm_land_debug" : {
        "time"  : "0:45:00",
        "tests" : (
            "ERS_D.f19_f19.IELM.elm-ic_f19_f19_ielm",
            "ERS_D.f09_g16.I1850ELMCN",
            "ERS_D.ne4pg2_oQU480.I20TRELM.elm-disableDynpftCheck",
            "ERS_D.f19_g16.I1850GSWCNPRDCTCBC.elm-ctc_f19_g16_I1850GSWCNPRDCTCBC",
            "ERS_D.f09_f09.IELM.elm-solar_rad",
            "ERS_D.f09_f09.IELM.elm-koch_snowflake",
            )
        },

    "e3sm_land_developer" : {
        "share" : True,
        "time"  : "0:45:00",
        "inherit" : ("e3sm_mosart_developer", "e3sm_land_exeshare", "e3sm_land_exenoshare", "e3sm_land_debug", "fates_elm_developer"),
        "tests" : (
            "ERS.f19_f19.I1850ELMCN",
            "ERS.f19_f19.I20TRELMCN",
            "SMS_Ld1.hcru_hcru.I1850CRUELMCN",
            "SMS_Ly5_P1x1.1x1_smallvilleIA.IELMCNCROP.elm-force_netcdf_pio",
            "ERS.f19_g16.I1850ELM.elm-betr",
            "ERS.f19_g16.I1850ELM.elm-vst",
            "ERS.f09_g16.I1850ELMCN.elm-bgcinterface",
            "SMS.r05_r05.I1850ELMCN.elm-qian_1948",
            "SMS_Ly5_P1x1.1x1_smallvilleIA.IELMCNCROP.elm-per_crop",
            "SMS_Ly2_P1x1.1x1_smallvilleIA.IELMCNCROP.elm-fan",
            "SMS.r05_r05.IELM.elm-topounit",
            "SMS.r05_r05.IELM.elm-topounit_im2",
            "ERS.ELM_USRDAT.I1850ELM.elm-usrdat",
            "ERS.r05_r05.IELM.elm-lnd_rof_2way",
            "ERS.r05_r05.IELM.elm-V2_ELM_MOSART_features",
            "ERS.ELM_USRDAT.IELM.elm-surface_water_dynamics",
            "ERS.ELM_USRDAT.IELM.elm-finetop_rad"
            )
        },

    "e3sm_atm_developer" : {
        "inherit" : ("eam_theta_pg2"),
        "tests"   : (
            "ERP_Ld3.ne4pg2_oQU480.F2010",
            "SMS_Ln9.ne4pg2_oQU480.F2010.eam-outfrq9s",
            "SMS.ne4pg2_oQU480.F2010.eam-cosplite",
            "SMS_R_Ld5.ne4_ne4.FSCM-ARM97.eam-scm",
            "SMS_D_Ln5.ne4pg2_oQU480.F2010",
            "SMS_Ln5.ne4pg2_oQU480.F2010",
            "ERS_D.ne4pg2_oQU480.F2010.eam-hommexx",
            "SMS_Ln9_P24x1.ne4_ne4.FDPSCREAM-ARM97",
            )
        },

    "e3sm_ice_developer" : {
        "tests"   : (
            "SMS_D_Ld1.TL319_IcoswISC30E3r5.DTESTM-JRA1p5.mpassi-jra_1958",
            "ERS_Ld5.T62_oQU240.DTESTM",
            "PEM_Ln5.T62_oQU240wLI.DTESTM",
            "PET_Ln5.T62_oQU240.DTESTM",
            )
        },

    "e3sm_cryo_developer" : {
        "tests"   : (
            "SMS_D_Ld1.TL319_IcoswISC30E3r5.GMPAS-JRA1p5-DIB-PISMF.mpaso-jra_1958",
            "ERS_Ld5.T62_oQU240wLI.GMPAS-DIB-IAF-PISMF",
            "PEM_Ln5.T62_oQU240wLI.GMPAS-DIB-IAF-PISMF",
            "PET_Ln5.T62_oQU240wLI.GMPAS-DIB-IAF-PISMF",
            "ERS_Ld5.T62_oQU240wLI.GMPAS-DIB-IAF-DISMF",
            "PEM_Ln5.T62_oQU240wLI.GMPAS-DIB-IAF-DISMF",
            "PET_Ln5.T62_oQU240wLI.GMPAS-DIB-IAF-DISMF",
            "ERS_Ld5.TL319_oQU240wLI_ais8to30.GMPAS-JRA1p5-DIB-PISMF-DIS.mpaso-ocn_glcshelf",
            "ERS_Ld5.TL319_oQU240wLI_ais8to30.GMPAS-JRA1p5-DIB-PISMF-SIS.mpaso-ocn_glcshelf",
            )
        },

    "e3sm_developer" : {
        "inherit" : ("e3sm_land_developer", "e3sm_atm_developer", "e3sm_ice_developer", "e3sm_cryo_developer"),
        "time"    : "0:45:00",
        "tests"   : (
            "ERS.ne4pg2_oQU480_rx1.A",
            "SEQ.f19_g16.X",
            "ERIO.ne4pg2_oQU480_rx1.A",
            "NCK.ne4pg2_oQU480_rx1.A",
            "SMS.ne4pg2_oQU480_rx1.A",
            "ERS_Ld5.T62_oQU120.CMPASO-NYF",
            "ERS.ne30pg2_r05_IcoswISC30E3r5_gis4to40.MALISIA",
            "ERS_Ld5.TL319_oQU240wLI_ais8to30.MPAS_LISIO_JRA1p5.mpaso-ocn_glcshelf",
            "SMS_P12x2.ne4pg2_oQU480.WCYCL1850NS.allactive-mach_mods",
            "ERS_Ln9.ne4pg2_ne4pg2.F2010-MMF1.eam-mmf_crmout",
            "ERS_Vmoab.ne4pg2_oQU480.WCYCL1850NS",
            "SMS_Lh4.ne4_ne4.F2010-SCREAMv1.eamxx-output-preset-1--eamxx-fixer_debug_output",
            "SMS_Lh4.ne4pg2_ne4pg2.F2010-SCREAMv1.eamxx-output-preset-1--eamxx-prod",
            )
        },

    #fates debug tests included in e3sm land developer test runs
    "fates_elm_debug" : {
        "tests" : (
            "SMS_D_Ld20.f45_f45.IELMFATES.elm-fates_rd",
            "ERS_D_Ld15.f45_g37.IELMFATES.elm-fates_cold_treedamage",
            )
        },

    #fates non-debug tests included in e3sm land developer test runs
    "fates_elm_developer" : {
        "inherit" : ("fates_elm_debug"),
        "tests" : (
            "ERS_Ld30.f45_f45.IELMFATES.elm-fates_satphen",
            "ERS_Ld30.f45_g37.IELMFATES.elm-fates_cold_sizeagemort",
            "SMS_Ld20.f45_f45.IELMFATES.elm-fates_eca",
            "SMS_Ld5_PS.f19_g16.IELMFATES.elm-fates_cold",
            )
        },

    #fates long duration tests runs
    "fates_long_tests" : {
        "time"    : "00:40:00",
        "tests"   : (
            "SMS_D_Lm6.f45_g37.IELMFATES.elm-fates_cold",
            "ERS_D_Ld390.ne4pg2_ne4pg2.IELMFATES.elm-fates_long",
            "ERS_Ld750.ne4pg2_ne4pg2.IELMFATES.elm-fates_cold_nocomp",
            )
        },

    #fates testmod coverage
    "fates_landuse" : {
        "time"    : "00:40:00",
        "tests"   : (
            "ERS_Ld60.f45_g37.IELMFATES.elm-fates_cold_logging",
            "ERS_D_Ld30.f45_g37.IELMFATES.elm-fates_cold_landuse",
            "ERS_D_Ld30.f45_g37.IELMFATES.elm-fates_cold_luh2",
            "ERS_D_Ld30.f45_g37.IELMFATES.elm-fates_cold_luh2harvestarea",
            "ERS_D_Ld30.f45_g37.IELMFATES.elm-fates_cold_luh2harvestmass",
            )
        },

    #fates testmod coverage
    "fates" : {
        "inherit" : ("fates_long_tests", "fates_elm_developer", "fates_landuse"),
        "tests" : (
            "ERP_Ld15.ne4pg2_ne4pg2.IELMFATES.elm-fates_cold_allvars",
            "ERP_Ld3.f09_g16.IELMFATES.elm-fates_cold",
            "ERP_D_Ld3.f19_g16.IELMFATES.elm-fates_cold",
            "ERS_D_Ld3_PS.f09_g16.IELMFATES.elm-fates_cold",
            "ERS_D_Ld5.f45_g37.IELMFATES.elm-fates_cold",
            "ERS_Ld30.f45_g37.IELMFATES.elm-fates_satphen",
            "ERS_Ld30.f45_g37.IELMFATES.elm-fates_cold_fixedbiogeo",
            "ERS_Ld30.f45_g37.IELMFATES.elm-fates_cold_nocomp",
            "ERS_Ld30.f45_g37.IELMFATES.elm-fates_cold_nocomp_fixedbiogeo",
            "ERS_Ld60.f45_g37.IELMFATES.elm-fates",
            "ERS_Ld60.f45_g37.IELMFATES.elm-fates_cold_nofire",
            "ERS_Ld60.f45_g37.IELMFATES.elm-fates_cold_st3",
            "ERS_Ld60.f45_g37.IELMFATES.elm-fates_cold_pphys",
            "SMS_D_Ld15.f45_g37.IELMFATES.elm-fates_cold_twostream",
            "ERS_Ld60.f45_g37.IELMFATES.elm-fates_cold_managedfire"
            )
        },

    #atmopheric tests for ftypes with 2 builds only
    "eam_preqx" : {
        "share"    : True,
        "time"     : "01:00:00",
        "tests"    : (
                 "SMS.ne4pg2_oQU480.F2010.eam-preqx_ftype0",
                 "SMS.ne4pg2_oQU480.F2010.eam-preqx_ftype1",
                 "SMS.ne4pg2_oQU480.F2010.eam-preqx_ftype4",
                 )
    },
    "eam_theta" : {
        "share"    : True,
        "time"     : "02:00:00",
        "tests"    : (
                 "SMS.ne4pg2_oQU480.F2010.eam-thetahy_ftype0",
                 "SMS.ne4pg2_oQU480.F2010.eam-thetahy_ftype1",
                 "SMS.ne4pg2_oQU480.F2010.eam-thetahy_ftype2",
                 "SMS.ne4pg2_oQU480.F2010.eam-thetahy_ftype2_energy",
                 "SMS.ne4pg2_oQU480.F2010.eam-thetahy_ftype4",
                 "SMS.ne4pg2_oQU480.F2010.eam-thetanh_ftype0",
                 "SMS.ne4pg2_oQU480.F2010.eam-thetanh_ftype1",
                 "SMS.ne4pg2_oQU480.F2010.eam-thetanh_ftype2",
                 "SMS.ne4pg2_oQU480.F2010.eam-thetanh_ftype4",
                 "SMS.ne4pg2_oQU480.F2010.eam-thetahy_sl",
                 "ERS.ne4pg2_oQU480.F2010.eam-thetahy_sl_nsubstep2",
                 "ERS.ne4pg2_oQU480.F2010.eam-thetahy_ftype2",
                 "ERS.ne4pg2_oQU480.F2010.eam-thetanh_ftype2",
                 )
    },
    "eam_theta_pg2" : {
        "share"    : True,
        "time"     : "02:00:00",
        "tests"    : (
                 "SMS_Ln5.ne4pg2_oQU480.F2010.eam-thetahy_pg2",
                 "SMS_Ln5.ne4pg2_oQU480.F2010.eam-thetahy_sl_pg2",
                 "ERS_Ld3.ne4pg2_oQU480.F2010.eam-thetahy_sl_pg2",
                 "SMS_Ln5.ne4pg2_oQU480.F2010.eam-thetahy_sl_pg2_ftype0",
                 "ERS_Ld3.ne4pg2_oQU480.F2010.eam-thetahy_sl_pg2_ftype0",
                 )
    },

    "e3sm_atm_integration" : {
        "inherit" : ("eam_preqx", "eam_theta"),
        "tests" : (
            "ERP_Ln9.ne4pg2_ne4pg2.FAQP",
            "SMS_Ld1.ne4pg2_ne4pg2.FAQP.eam-clubb_only",
            "ERP_Ln9.ne4pg2_ne4pg2.FRCE",
            "PET_Ln5.ne4pg2_oQU480.F2010.allactive-mach-pet",
            "PEM_Ln5.ne4pg2_oQU480.F2010",
            "SMS_D_Ln5.ne4pg2_oQU480.F2010.eam-cosplite_nhtfrq5",
            "SMS_Ln1.ne4pg2_oQU480.F2010.eam-chem_pp",
            "SMS_Ln5.ne30pg2_r05_IcoswISC30E3r5.BGCEXP_LNDATM_CNPRDCTC_20TR",
            "SMS_Ln5.ne30pg2_r05_IcoswISC30E3r5.BGCEXP_LNDATM_CNPRDCTC_1850",
            "SMS_D_Ln5.ne4pg2_oQU480.F2010.eam-clubb_sp",
            "ERS_Ld5.ne4pg2_oQU480.F2010.eam-rrtmgp",
            "ERS_Ld5.ne4pg2_oQU480.F2010.eam-rrtmgpxx",
            "REP_Ln5.ne4pg2_oQU480.F2010",
            "SMS_Ld3.ne4pg2_oQU480.F2010.eam-thetahy_sl_pg2_mass",
            "ERP_Ld3.ne4pg2_ne4pg2.FIDEAL.allactive-pioroot1",
            "ERS_Ld5.ne4pg2_oQU480.F2010.eam-sathist_F2010",
            "ERS_Ld5.ne4pg2_oQU480.F2010xx-ZM",
            )
        },

    #e3sm MMF tests for development
    "e3sm_mmf_integration" : {
        "tests" : (
            "ERP_Ln9.ne4pg2_oQU480.WCYCL20TRNS-MMF1.allactive-mmf_fixed_subcycle",
            "ERS_Ln9.ne4pg2_ne4pg2.FRCE-MMF1.eam-cosp_nhtfrq9",
            "SMS_Ln5.ne4_ne4.FSCM-ARM97-MMF1",
            )
        },

    #e3sm tests for RRM grids
    "e3sm_rrm" : {
        "tests" : (
            "SMS_D_Ln5.conusx4v1pg2_r05_IcoswISC30E3r5.F2010",
            )
        },

    "e3sm_integration" : {
        "inherit" : ("e3sm_developer", "e3sm_atm_integration", "e3sm_mmf_integration", "e3sm_rrm"),
        "time"    : "03:00:00",
        "tests"   : (
            "ERS.ne4pg2_oQU480.WCYCL1850NS",
            "SMS_D_Ld1.ne30pg2_r05_IcoswISC30E3r5.WCYCL1850.allactive-wcprod",
            "SMS_D_Ld1.ne30pg2_r05_IcoswISC30E3r5.WCYCLSSP370.allactive-wcprodssp",
            "ERS_Ld3.ne4pg2_oQU480.F2010",
            "NCK.ne4pg2_oQU480.WCYCL1850NS",
            "PET.f19_g16.X.allactive-mach-pet",
            "PET.ne4pg2_oQU480_rx1.A.allactive-mach-pet",
            "PET_Ln9_PS.ne30pg2_r05_IcoswISC30E3r5.WCYCL1850.allactive-mach-pet",
            "PEM_Ln9.ne30pg2_r05_IcoswISC30E3r5.WCYCL1850",
            "ERP_Ld3.ne30pg2_r05_IcoswISC30E3r5.WCYCL1850.allactive-pioroot1",
            "SMS_Ld2.ne30pg2_r05_IcoswISC30E3r5.BGCEXP_CNTL_CNPECACNT_1850.elm-bgcexp",
            "SMS_Ld2.ne30pg2_r05_IcoswISC30E3r5.BGCEXP_CNTL_CNPRDCTC_1850.elm-bgcexp",
            "SMS_D_Ld3.T62_oQU120.CMPASO-IAF",
            "SMS_Ln5.ne30pg2_ne30pg2.F2010-SCREAM-LR-DYAMOND2",
            "ERS_Ld3.ne30pg2_r05_IcoswISC30E3r5.WCYCL1850.allactive-nlmaps",
            "SMS_D_Ld1.ne30pg2_r05_IcoswISC30E3r5.CRYO1850-DISMF",
            "ERS.hcru_hcru.I20TRGSWCNPRDCTCBC.elm-erosion",
            "ERS.ne30pg2_r05_IcoswISC30E3r5.GPMPAS-JRA.mosart-rof_ocn_2way",
            )
        },

    #atmopheric tests for extra coverage
    "e3sm_atm_extra_coverage" : {
        "tests" : (
            "SMS_Lm1.ne4pg2_oQU480.F2010",
            "ERS_Ld31.ne4pg2_oQU480.F2010",
            "ERP_Ld90.ne4pg2_oQU480.F2010",
            "SMS_D_Ln5.ne30pg2_r05_IcoswISC30E3r5.F2010",
            "ERP_Ld3.ne30pg2_r05_IcoswISC30E3r5.F2010.allactive-pioroot1",
            "SMS_Ly1.ne4pg2_oQU480.F2010",
            "SMS_D_Ln5.ne45pg2_ne45pg2.FAQP",
            )
        },

    #atmopheric tests for hi-res
    "e3sm_atm_hi_res" : {
        "time" : "01:30:00",
        "tests" : "SMS.ne120pg2_r025_RRSwISC6to18E3r5.F2010"
        },

    "e3sm_hi_res" : {
        "inherit" : "e3sm_atm_hi_res",
        "tests"   : (
            "SMS_Ld3.ne120pg2_r025_RRSwISC6to18E3r5.WCYCL1850NS.eam-cosplite",
            "SMS.T62_SOwISC12to30E3r3.GMPAS-IAF",
            )
        },

    "e3sm_ocnice_stealth_features" : {
        "tests" : (
            "SMS_D_Ld1.T62_oQU240wLI.GMPAS-IAF-PISMF.mpaso-impl_top_drag",
            "SMS_D_Ld1.T62_oQU240.GMPAS-IAF.mpaso-harmonic_mean_drag",
            "SMS_D_Ld1.T62_oQU240.GMPAS-IAF.mpaso-upwind_advection",
            "SMS_D_Ld1.T62_oQU240.GMPAS-IAF.mpaso-freshwater_tracers",
            "SMS_D_Ld1.T62_oQU240.GMPAS-IAF.mpaso-lat_dep_diffusivity",
            "ERS_Ld5_D.T62_oQU240.GMPAS-IAF.mpaso-conservation_check",
            )
        },

    "e3sm_ocnice_extra_coverage" : {
        "inherit" : ("e3sm_ocnice_stealth_features"),
        "tests" : (
            "ERS_P480_Ld5.TL319_IcoswISC30E3r5.GMPAS-JRA1p5-DIB-PISMF.mpaso-jra_1958",
            "PEM_P480_Ld5.TL319_IcoswISC30E3r5.GMPAS-JRA1p5-DIB-PISMF.mpaso-jra_1958",
            "SMS_P480_Ld5.TL319_IcoswISC30E3r5.GMPAS-JRA1p5-DIB-PISMF-TMIX.mpaso-jra_1958",
            )
        },

    "e3sm_extra_coverage" : {
        "inherit" : ("e3sm_atm_extra_coverage", "e3sm_ocnice_extra_coverage"),
        "tests"   : (
            "SMS_D_Ln3.TL319_EC30to60E2r2_wQU225EC30to60E2r2.GMPAS-JRA1p5-WW3.ww3-jra_1958",
            )
        },

    # e3sm_eamxx_v1_long has empty inherit - this is valid
    "e3sm_eamxx_v1_long" : {
        "time"  : "01:00:00",
        "inherit" : (
        ),
        "tests" : (
            "RCS_C4.ne30pg2_ne30pg2.F2010-SCREAMv1.eamxx-perturb",
            "RCS_C4.ne4pg2_ne4pg2.F2010-SCREAMv1.eamxx-perturb",
            "ERP_D_Lh182.ne4pg2_ne4pg2.F2010-SCREAMv1",
            "ERS_Ln362.ne30pg2_ne30pg2.F2010-SCREAMv1"
            )
    },

    "e3sm_gcam_developer" : {
        "time"  : "1:00:00",
        "tests" : (
            "SMS.ne30pg2_f09_oEC60to30v3.SSP245_ZATM_BGC",
            "ERS.ne30pg2_f09_oEC60to30v3.SSP245_ZATM_BGC",
            )
    },
}
