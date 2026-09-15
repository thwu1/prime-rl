Attributes {
  time {
    String _CoordinateAxisType "Time";
    Float64 actual_range 9.99E8, 1.1E9;
    String axis "T";
    String ioos_category "Time";
    String long_name "Centered Time";
    String standard_name "time";
    String units "seconds since 1970-01-01T00:00:00Z";
  }
  altitude {
    String _CoordinateAxisType "Height";
    Float64 actual_range 10.0, 10.0;
    String axis "Z";
    String ioos_category "Location";
    String long_name "Altitude";
    String standard_name "altitude";
    String units "m";
  }
  lat {
    String _CoordinateAxisType "Lat";
    Float64 actual_range -89.875, 89.875;
    String axis "Y";
    String ioos_category "Location";
    String long_name "Latitude";
    String standard_name "latitude";
    String units "degrees_north";
  }
  lon {
    String _CoordinateAxisType "Lon";
    Float64 actual_range 0.125, 359.875;
    String axis "X";
    String ioos_category "Location";
    String long_name "Longitude";
    String standard_name "longitude";
    String units "degrees_east";
  }
  ux10 {
    Float32 _FillValue -9999999.0;
    String ioos_category "Wind";
    String long_name "Zonal Wind Speed at 10m";
    String standard_name "x_wind";
    String units "m s-1";
  }
  NC_GLOBAL {
    String cdm_data_type "Grid";
    String Conventions "COARDS, CF-1.6, ACDD-1.3";
    String institution "NOAA NMFS SWFSC ERD";
    String title "Wind, QuikSCAT, Zonal, Global, Science Quality";
  }
}
