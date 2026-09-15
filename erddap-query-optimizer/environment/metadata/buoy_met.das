Attributes {
  s {
    station {
      String cf_role "timeseries_id";
      String ioos_category "Identifier";
      String long_name "Station Name";
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
      Float64 actual_range -90.0, 90.0;
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
    sea_surface_temperature {
      Float64 colorBarMaximum 32.0;
      Float64 colorBarMinimum 0.0;
      String ioos_category "Temperature";
      String long_name "Sea Surface Temperature";
      String standard_name "sea_surface_temperature";
      String units "degree_C";
    }
    air_temperature {
      Float64 colorBarMaximum 40.0;
      Float64 colorBarMinimum -10.0;
      String ioos_category "Temperature";
      String long_name "Air Temperature";
      String standard_name "air_temperature";
      String units "degree_C";
    }
    wind_speed {
      Float64 colorBarMaximum 15.0;
      Float64 colorBarMinimum 0.0;
      String ioos_category "Wind";
      String long_name "Wind Speed";
      String standard_name "wind_speed";
      String units "m s-1";
    }
  }
  NC_GLOBAL {
    String cdm_data_type "TimeSeries";
    String cdm_timeseries_variables "station, latitude, longitude";
    String Conventions "CF-1.6, COARDS, ACDD-1.3";
    Float64 geospatial_lat_max 90.0;
    Float64 geospatial_lat_min -90.0;
    String geospatial_lat_units "degrees_north";
    Float64 geospatial_lon_max 180.0;
    Float64 geospatial_lon_min -180.0;
    String geospatial_lon_units "degrees_east";
    String id "buoy_met";
    String institution "NOAA NDBC";
    String summary "Meteorological data from NDBC buoys";
    String title "NDBC Standard Meteorological Buoy Data";
    Float64 Westernmost_Easting -180.0;
  }
}
