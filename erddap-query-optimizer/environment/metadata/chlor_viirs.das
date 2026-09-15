Attributes {
  time {
    String _CoordinateAxisType "Time";
    Float64 actual_range 1.3569e+9, 1.7150400e+9;
    String axis "T";
    String ioos_category "Time";
    String long_name "Centered Time";
    String standard_name "time";
    String time_origin "01-JAN-1970 00:00:00";
    String units "seconds since 1970-01-01T00:00:00Z";
    Float64 spacing 691200.0;
  }
  altitude {
    String _CoordinateAxisType "Height";
    Float64 actual_range 0.0, 0.0;
    String axis "Z";
    String ioos_category "Location";
    String long_name "Altitude";
    String positive "up";
    String standard_name "altitude";
    String units "m";
  }
  latitude {
    String _CoordinateAxisType "Lat";
    Float64 actual_range -60.0, 60.0;
    String axis "Y";
    String ioos_category "Location";
    String long_name "Latitude";
    String point_spacing "even";
    String standard_name "latitude";
    String units "degrees_north";
    Float64 spacing 0.05;
  }
  longitude {
    String _CoordinateAxisType "Lon";
    Float64 actual_range -179.975, 179.975;
    String axis "X";
    String ioos_category "Location";
    String long_name "Longitude";
    String point_spacing "even";
    String standard_name "longitude";
    String units "degrees_east";
    Float64 spacing 0.05;
  }
  chlor_a {
    String ioos_category "Ocean Color";
    String long_name "Chlorophyll-a Concentration";
    String standard_name "mass_concentration_of_chlorophyll_a_in_sea_water";
    String units "mg m-3";
    String ancillary_variables "quality_flags";
  }
  quality_flags {
    String ioos_category "Quality";
    String long_name "Quality Control Flags";
    String comment "Bitwise quality flags for chlorophyll retrievals";
  }
  NC_GLOBAL {
    String cdm_data_type "Grid";
    String Conventions "CF-1.6, COARDS, ACDD-1.3";
    Float64 geospatial_lat_max 60.0;
    Float64 geospatial_lat_min -60.0;
    Float64 geospatial_lat_resolution 0.05;
    String geospatial_lat_units "degrees_north";
    Float64 geospatial_lon_max 179.975;
    Float64 geospatial_lon_min -179.975;
    Float64 geospatial_lon_resolution 0.05;
    String geospatial_lon_units "degrees_east";
    String id "chlor_viirs";
    String institution "NASA/GSFC/OBPG";
    String title "VIIRS Level-3 Chlorophyll-a Concentration";
  }
}
