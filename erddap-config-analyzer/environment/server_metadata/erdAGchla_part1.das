Attributes {
  time {
    String _CoordinateAxisType "Time";
    Float64 actual_range 1.0E9, 1.5E9;
    String axis "T";
    String ioos_category "Time";
    String long_name "Centered Time";
    String standard_name "time";
    String units "seconds since 1970-01-01T00:00:00Z";
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
  chlor_a {
    Float32 _FillValue -9999999.0;
    String long_name "Chlorophyll-a Concentration";
    String standard_name "chlorophyll_concentration";
    String units "mg m-3";
  }
  NC_GLOBAL {
    String cdm_data_type "Grid";
    String Conventions "COARDS, CF-1.6, ACDD-1.3";
    String institution "NOAA CoastWatch";
    String title "Chlorophyll, Aqua MODIS, Global (Part 1)";
  }
}
