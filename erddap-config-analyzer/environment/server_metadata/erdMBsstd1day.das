Attributes {
  time {
    String _CoordinateAxisType "Time";
    Float64 actual_range 1.0259568E9, 1.7020512E9;
    String axis "T";
    String ioos_category "Time";
    String long_name "Centered Time";
    String standard_name "time";
    String time_origin "01-JAN-1970 00:00:00";
    String units "seconds since 1970-01-01T00:00:00Z";
  }
  altitude {
    String _CoordinateAxisType "Height";
    String _CoordinateZisPositive "up";
    Float64 actual_range 0.0, 0.0;
    String axis "Z";
    String ioos_category "Location";
    String long_name "Altitude";
    String positive "up";
    String standard_name "altitude";
    String units "m";
  }
  lat {
    String _CoordinateAxisType "Lat";
    Float64 actual_range 22.0, 51.0;
    String axis "Y";
    String ioos_category "Location";
    String long_name "Latitude";
    String standard_name "latitude";
    String units "degrees_north";
  }
  lon {
    String _CoordinateAxisType "Lon";
    Float64 actual_range -135.0, -105.0;
    String axis "X";
    String ioos_category "Location";
    String long_name "Longitude";
    String standard_name "longitude";
    String units "degrees_east";
  }
  MBsstd {
    Float32 _FillValue -9999999.0;
    Float64 colorBarMaximum 32.0;
    Float64 colorBarMinimum 0.0;
    String ioos_category "Temperature";
    String long_name "Sea Surface Temperature";
    String standard_name "sea_surface_temperature";
    String units "deg_C";
  }
  quality_level {
    Byte _FillValue -128;
    Byte valid_range 0, 5;
    String long_name "Quality Level";
    String comment "0=no data 1=bad 2=suspect 3=acceptable 4=good 5=excellent";
  }
  NC_GLOBAL {
    String cdm_data_type "Grid";
    String Conventions "COARDS, CF-1.6, ACDD-1.3";
    String creator_email "erd.data@noaa.gov";
    String creator_name "NOAA NMFS SWFSC ERD";
    String institution "NOAA NMFS SWFSC ERD";
    String title "SST, Aqua MODIS, NPP, 0.025 deg, West US, Day and Night";
  }
}
