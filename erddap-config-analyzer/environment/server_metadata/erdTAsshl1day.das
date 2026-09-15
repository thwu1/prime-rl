Attributes {
  time {
    String _CoordinateAxisType "Time";
    Float64 actual_range 1.1E9, 1.7E9;
    String axis "T";
    String ioos_category "Time";
    String long_name "Time";
    String standard_name "time";
    String units "seconds since 1970-01-01T00:00:00Z";
  }
  altitude {
    String _CoordinateAxisType "Height";
    Float64 actual_range 0.0, 0.0;
    String axis "Z";
    String ioos_category "Location";
    String long_name "Altitude";
    String standard_name "altitude";
    String units "m";
  }
  lat {
    String _CoordinateAxisType "Lat";
    Float64 actual_range -90.0, 90.0;
    String axis "Y";
    String ioos_category "Location";
    String long_name "Latitude";
    String standard_name "latitude";
    String units "degrees_north";
  }
  lon {
    String _CoordinateAxisType "Lon";
    Float64 actual_range -180.0, 180.0;
    String axis "X";
    String ioos_category "Location";
    String long_name "Longitude";
    String standard_name "longitude";
    String units "degrees_east";
  }
  TAsshl {
    Float64 _FillValue -1.0E34;
    String ioos_category "Sea Level";
    String long_name "Sea Surface Height";
    String standard_name "sea_surface_height_above_geoid";
    String units "m";
  }
  NC_GLOBAL {
    String cdm_data_type "Grid";
    String Conventions "COARDS, CF-1.6, ACDD-1.3";
    String institution "NOAA NMFS SWFSC ERD";
    String title "SSH Absolute, Aviso, 0.25 deg, Global";
  }
}
