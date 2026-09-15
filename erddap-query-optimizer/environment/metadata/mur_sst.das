Attributes {
  time {
    String _CoordinateAxisType "Time";
    Float64 actual_range 1.0228896e+9, 1.7231904e+9;
    String axis "T";
    String ioos_category "Time";
    String long_name "Centered Time";
    String standard_name "time";
    String time_origin "01-JAN-1970 00:00:00";
    String units "seconds since 1970-01-01T00:00:00Z";
    Float64 spacing 86400.0;
  }
  latitude {
    String _CoordinateAxisType "Lat";
    Float64 actual_range -89.99, 89.99;
    String axis "Y";
    String ioos_category "Location";
    String long_name "Latitude";
    String point_spacing "even";
    String standard_name "latitude";
    String units "degrees_north";
    Float64 spacing 0.01;
  }
  longitude {
    String _CoordinateAxisType "Lon";
    Float64 actual_range 0.01, 359.99;
    String axis "X";
    String ioos_category "Location";
    String long_name "Longitude";
    String point_spacing "even";
    String standard_name "longitude";
    String units "degrees_east";
    Float64 spacing 0.01;
  }
  analysed_sst {
    String ioos_category "Temperature";
    String long_name "Analysed Sea Surface Temperature";
    String standard_name "sea_surface_temperature";
    String units "kelvin";
    String ancillary_variables "analysis_error mask";
  }
  analysis_error {
    String ioos_category "Statistics";
    String long_name "Estimated Error Standard Deviation of analysed_sst";
    String units "kelvin";
  }
  mask {
    String ioos_category "Quality";
    String long_name "Sea/Land/Ice Mask";
    String comment "1=ocean, 2=land, 5=lake, 9=ice";
  }
  NC_GLOBAL {
    String cdm_data_type "Grid";
    String Conventions "CF-1.6, COARDS, ACDD-1.3";
    Float64 geospatial_lat_max 89.99;
    Float64 geospatial_lat_min -89.99;
    Float64 geospatial_lat_resolution 0.01;
    String geospatial_lat_units "degrees_north";
    Float64 geospatial_lon_max 359.99;
    Float64 geospatial_lon_min 0.01;
    Float64 geospatial_lon_resolution 0.01;
    String geospatial_lon_units "degrees_east";
    String id "mur_sst";
    String institution "NASA/JPL";
    String title "Multi-scale Ultra-high Resolution SST Analysis";
  }
}
