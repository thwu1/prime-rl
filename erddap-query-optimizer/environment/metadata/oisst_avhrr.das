Attributes {
  time {
    String _CoordinateAxisType "Time";
    Float64 actual_range 6.2208e+8, 1.7231904e+9;
    String axis "T";
    String ioos_category "Time";
    String long_name "Centered Time";
    String standard_name "time";
    String time_origin "01-JAN-1970 00:00:00";
    String units "seconds since 1970-01-01T00:00:00Z";
    Float64 spacing 86400.0;
  }
  zlev {
    String _CoordinateAxisType "Height";
    Float64 actual_range 0.0, 0.0;
    String axis "Z";
    String ioos_category "Location";
    String long_name "Depth";
    String positive "down";
    String standard_name "depth";
    String units "m";
  }
  latitude {
    String _CoordinateAxisType "Lat";
    Float64 actual_range -89.875, 89.875;
    String axis "Y";
    String ioos_category "Location";
    String long_name "Latitude";
    String point_spacing "even";
    String standard_name "latitude";
    String units "degrees_north";
    Float64 spacing 0.25;
  }
  longitude {
    String _CoordinateAxisType "Lon";
    Float64 actual_range 0.125, 359.875;
    String axis "X";
    String ioos_category "Location";
    String long_name "Longitude";
    String point_spacing "even";
    String standard_name "longitude";
    String units "degrees_east";
    Float64 spacing 0.25;
  }
  sst {
    String ioos_category "Temperature";
    String long_name "Daily Sea Surface Temperature";
    String standard_name "sea_surface_temperature";
    String units "degree_C";
  }
  err {
    String ioos_category "Statistics";
    String long_name "Estimated Error Standard Deviation";
    String units "degree_C";
  }
  NC_GLOBAL {
    String cdm_data_type "Grid";
    String Conventions "CF-1.6, COARDS, ACDD-1.3";
    Float64 geospatial_lat_max 89.875;
    Float64 geospatial_lat_min -89.875;
    Float64 geospatial_lat_resolution 0.25;
    String geospatial_lat_units "degrees_north";
    Float64 geospatial_lon_max 359.875;
    Float64 geospatial_lon_min 0.125;
    Float64 geospatial_lon_resolution 0.25;
    String geospatial_lon_units "degrees_east";
    String id "oisst_avhrr";
    String institution "NOAA/NCEI";
    String title "NOAA Optimum Interpolation SST V2";
  }
}
