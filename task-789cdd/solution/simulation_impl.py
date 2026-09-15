"""
Simulation Engine - Solution Implementation

Discrete-event clinical case simulation with conditional event processing.
"""
from order_matcher import OrderMatcher


class SimulationEngine:
    VALID_LOCATIONS = [
        "office",
        "emergency_department",
        "inpatient_unit",
        "intensive_care_unit",
        "home",
    ]

    def __init__(self, case_definition: dict, catalog: list[dict]):
        self.case = case_definition
        self.catalog = catalog
        self.matcher = OrderMatcher(catalog)

        # Build catalog lookup by canonical name
        self.catalog_lookup = {}
        for entry in catalog:
            self.catalog_lookup[entry["canonical_name"]] = entry

        # Initialize patient state from case definition
        init = case_definition["initial_state"]
        self.state = {
            "vitals": dict(init["vitals"]),
            "active_medications": list(init.get("active_medications", [])),
            "pending_orders": [],
            "completed_orders": [],
            "location": init["location"],
            "current_time": 0,
            "narrative_log": [{"time": 0, "text": init["presenting_narrative"]}],
            "flags": dict(init.get("flags", {})),
        }

        # Deep copy events and sort by trigger time
        self.events = []
        for e in case_definition.get("events", []):
            self.events.append(
                {
                    "trigger_time": e["trigger_time"],
                    "condition": e.get("condition"),
                    "effects": e.get("effects", {}),
                    "narrative": e.get("narrative", ""),
                    "fired": False,
                }
            )
        self.events.sort(key=lambda e: e["trigger_time"])

        # Order results lookup
        self.order_results = case_definition.get("order_results", {})

        # Track placed order canonical names (for condition evaluation)
        self.placed_order_names = set()

        # Simulation transcript
        self.transcript = []

    def _evaluate_condition(self, condition) -> bool:
        """Recursively evaluate a condition expression."""
        if condition is None:
            return True

        ctype = condition.get("type", "")

        if ctype == "has_order":
            return condition["order"] in self.placed_order_names

        elif ctype == "not":
            return not self._evaluate_condition(condition["condition"])

        elif ctype == "and":
            return all(
                self._evaluate_condition(c) for c in condition["conditions"]
            )

        elif ctype == "or":
            return any(
                self._evaluate_condition(c) for c in condition["conditions"]
            )

        elif ctype == "location_is":
            return self.state["location"] == condition["location"]

        elif ctype == "flag_set":
            return bool(self.state["flags"].get(condition["flag"], False))

        return False

    def _process_events_at(self, t: int) -> list[str]:
        """Process events whose trigger_time equals t. Return fired narratives."""
        fired_narratives = []

        for event in self.events:
            if event["fired"] or event["trigger_time"] != t:
                continue

            if self._evaluate_condition(event["condition"]):
                event["fired"] = True
                effects = event["effects"]

                # Apply vital changes (absolute values)
                if "vitals" in effects:
                    for k, v in effects["vitals"].items():
                        self.state["vitals"][k] = v

                # Set flags
                if "flags" in effects:
                    self.state["flags"].update(effects["flags"])

                # Record narrative
                if event["narrative"]:
                    self.state["narrative_log"].append(
                        {"time": t, "text": event["narrative"]}
                    )
                    fired_narratives.append(event["narrative"])

        return fired_narratives

    def _deliver_results_at(self, t: int) -> list[str]:
        """Deliver results for pending orders whose report_at <= t."""
        delivered = []
        still_pending = []

        for po in self.state["pending_orders"]:
            if po["report_at"] <= t and not po.get("delivered", False):
                po["delivered"] = True
                if po.get("result") is None:
                    po["result"] = self.order_results.get(
                        po["canonical_name"],
                        f"{po['canonical_name']}: Results within normal limits.",
                    )
                self.state["completed_orders"].append(po)
                delivered.append(po["canonical_name"])
            else:
                still_pending.append(po)

        self.state["pending_orders"] = still_pending
        return delivered

    def place_order(self, raw_text: str) -> dict:
        matches = self.matcher.match(raw_text, location=self.state["location"])

        if not matches or matches[0]["score"] < 0.4:
            return {
                "status": "rejected",
                "canonical_name": None,
                "report_time": None,
                "message": f"Order not recognized: '{raw_text}'",
            }

        best = matches[0]
        canonical = best["canonical_name"]
        cat_entry = self.catalog_lookup.get(canonical, {})
        proc_time = cat_entry.get("processing_time_minutes", 0)
        report_time = self.state["current_time"] + proc_time

        order = {
            "raw_text": raw_text,
            "canonical_name": canonical,
            "category": best["category"],
            "placed_at": self.state["current_time"],
            "report_at": report_time,
            "location": self.state["location"],
            "result": None,
            "delivered": False,
        }

        if proc_time == 0:
            order["delivered"] = True
            order["result"] = self.order_results.get(
                canonical, f"{canonical} administered/initiated."
            )
            self.state["completed_orders"].append(order)
            if best["category"] == "medication":
                self.state["active_medications"].append(canonical)
        else:
            self.state["pending_orders"].append(order)

        self.placed_order_names.add(canonical)

        self.transcript.append(
            {
                "action_type": "order",
                "timestamp": self.state["current_time"],
                "details": {
                    "canonical_name": canonical,
                    "raw_text": raw_text,
                    "category": best["category"],
                },
            }
        )

        return {
            "status": "accepted",
            "canonical_name": canonical,
            "report_time": report_time,
            "message": f"Order placed: {canonical}",
        }

    def advance_clock(self, minutes: int) -> dict:
        old_time = self.state["current_time"]
        max_time = self.case.get("max_simulated_time", 999999)
        new_time = min(old_time + minutes, max_time)

        all_events_fired = []
        all_results = []

        # Process minute by minute
        for t in range(old_time + 1, new_time + 1):
            self.state["current_time"] = t

            # Evaluate events at this time
            fired = self._process_events_at(t)
            all_events_fired.extend(fired)

            # Deliver pending order results
            delivered = self._deliver_results_at(t)
            all_results.extend(delivered)

        self.state["current_time"] = new_time

        self.transcript.append(
            {
                "action_type": "advance_clock",
                "timestamp": new_time,
                "details": {"minutes": minutes, "from_time": old_time},
            }
        )

        return {
            "new_time": new_time,
            "events_fired": all_events_fired,
            "results_available": all_results,
            "patient_update": (
                "; ".join(all_events_fired)
                if all_events_fired
                else "No new updates."
            ),
        }

    def change_location(self, location: str) -> dict:
        if location not in self.VALID_LOCATIONS:
            return {
                "status": "failure",
                "message": f"Invalid location: {location}",
            }

        old_location = self.state["location"]
        self.state["location"] = location

        self.transcript.append(
            {
                "action_type": "change_location",
                "timestamp": self.state["current_time"],
                "details": {
                    "location": location,
                    "from_location": old_location,
                },
            }
        )

        self.state["narrative_log"].append(
            {
                "time": self.state["current_time"],
                "text": f"Patient transferred from {old_location} to {location}.",
            }
        )

        return {
            "status": "success",
            "message": f"Patient transferred to {location}",
        }

    def get_state(self) -> dict:
        return {
            "vitals": dict(self.state["vitals"]),
            "active_medications": list(self.state["active_medications"]),
            "pending_orders": [dict(po) for po in self.state["pending_orders"]],
            "completed_orders": [dict(co) for co in self.state["completed_orders"]],
            "location": self.state["location"],
            "current_time": self.state["current_time"],
            "narrative_log": list(self.state["narrative_log"]),
            "flags": dict(self.state["flags"]),
        }

    def get_transcript(self) -> list[dict]:
        return list(self.transcript)
