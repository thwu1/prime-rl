#
# jq program: receives {"input": <original_input>, "output": <mechcalc_output>}
# produces safety report with governing safety, required safety, and margin per module

.input as $in | .output as $out |

# Determine buckling governing safety based on zone
($out.buckling.zone) as $zone |
(if $zone == "elastic" then $out.buckling.safety_euler
 elif $zone == "inelastic" then $out.buckling.safety_johnson
 else ($in.buckling.material_yield_MPa / ($in.buckling.force_kN * 1000 / $out.buckling.area_mm2))
 end) as $buck_gov |

{
  modules: [
    {
      name: "bolt",
      pass: $out.bolt.pass,
      governing_safety: $out.bolt.safety_yield,
      required_safety: $in.bolt.safety_yield_desired,
      margin_pct: (($out.bolt.safety_yield / $in.bolt.safety_yield_desired - 1) * 100)
    },
    {
      name: "buckling",
      pass: $out.buckling.pass,
      governing_safety: $buck_gov,
      required_safety: $in.buckling.safety_desired,
      margin_pct: (($buck_gov / $in.buckling.safety_desired - 1) * 100)
    },
    {
      name: "vbelt",
      pass: $out.vbelt.pass,
      governing_safety: ($out.vbelt.wrap_angle_small_deg / 90),
      required_safety: 1.0,
      margin_pct: (($out.vbelt.wrap_angle_small_deg / 90 - 1) * 100)
    }
  ],
  overall_pass: ($out.bolt.pass and $out.buckling.pass and $out.vbelt.pass),
  min_margin_pct: ([
    (($out.bolt.safety_yield / $in.bolt.safety_yield_desired - 1) * 100),
    (($buck_gov / $in.buckling.safety_desired - 1) * 100),
    (($out.vbelt.wrap_angle_small_deg / 90 - 1) * 100)
  ] | min)
}
