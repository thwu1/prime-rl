Attributes {
  s {
    float_id {
      String cf_role "trajectory_id";
      String ioos_category "Identifier";
      String long_name "Float Identifier";
    }
    time {
      String _CoordinateAxisType "Time";
      String axis "T";
      String ioos_category "Time";
      String long_name "Time";
      String standard_name "time";
      String time_origin "01-JAN-1970 00:00:00";
      String units "seconds since 1970-01-01T00:00:00Z";
    }
    latitude {
      String _CoordinateAxisType "Lat";
      Float64 actual_range -65.0, 65.0;
      String axis "Y";
      String ioos_category "Location";
      String long_name "Latitude";
      String standard_name "latitude";
      String units "degrees_north";
    }
    longitude {
      String _CoordinateAxisType "Lon";
      Float64 actual_range -180.0, 180.0;
      String axis "X";
      String ioos_category "Location";
      String long_name "Longitude";
      String standard_name "longitude";
      String units "degrees_east";
    }
    temp {
      String ioos_category "Temperature";
      String long_name "Sea Water Temperature";
      String standard_name "sea_water_temperature";
      String units "degree_C";
    }
    psal {
      String ioos_category "Salinity";
      String long_name "Practical Salinity";
      String standard_name "sea_water_practical_salinity";
      String units "PSU";
    }
    pres {
      String ioos_category "Pressure";
      String long_name "Sea Water Pressure";
      String standard_name "sea_water_pressure";
      String units "decibar";
    }
    temp_qc {
      String ioos_category "Quality";
      String long_name "Temperature Quality Flag";
      String conventions "Argo reference table 2";
      String flag_values "0, 1, 2, 3, 4, 5, 8, 9";
      String flag_meanings "no_qc good probably_good probably_bad bad changed interpolated missing";
    }
  }
  NC_GLOBAL {
    String cdm_data_type "Trajectory";
    String Conventions "CF-1.6, COARDS, ACDD-1.3";
    Float64 geospatial_lat_max 65.0;
    Float64 geospatial_lat_min -65.0;
    String geospatial_lat_units "degrees_north";
    Float64 geospatial_lon_max 180.0;
    Float64 geospatial_lon_min -180.0;
    String geospatial_lon_units "degrees_east";
    String id "argo_profile";
    String institution "Argo";
    String title "Argo Float Profiles";
  }
}
