def in_range(lo; hi): . >= lo and . <= hi;

(
  has("semi_major_axis_km") and
  has("eccentricity") and
  has("inclination_deg") and
  has("argument_of_perigee_deg") and
  has("nodal_period_s") and
  has("ground_track_spacing_km") and
  has("max_altitude_variation_m") and
  has("altitude_at_equator_ascending_km") and
  has("sun_synchronous_raan_rate_deg_day")
) and
(
  (.semi_major_axis_km | type) == "number" and
  (.eccentricity | type) == "number" and
  (.inclination_deg | type) == "number" and
  (.argument_of_perigee_deg | type) == "number" and
  (.nodal_period_s | type) == "number" and
  (.ground_track_spacing_km | type) == "number" and
  (.max_altitude_variation_m | type) == "number" and
  (.altitude_at_equator_ascending_km | type) == "number" and
  (.sun_synchronous_raan_rate_deg_day | type) == "number"
) and
(.semi_major_axis_km | in_range(7100; 7200)) and
(.eccentricity | in_range(0.0001; 0.01)) and
(.inclination_deg | in_range(95; 102)) and
(.argument_of_perigee_deg | in_range(89.5; 90.5)) and
(.nodal_period_s | in_range(5900; 6200)) and
(.ground_track_spacing_km | in_range(200; 230)) and
(.sun_synchronous_raan_rate_deg_day | in_range(0.980; 0.990))
