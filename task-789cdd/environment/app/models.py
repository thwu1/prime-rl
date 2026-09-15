"""
Data models for the CCS Clinical Simulation Engine.

Reference definitions for the data structures used across all modules.
These are provided for documentation; implementations may use dicts directly.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Location(Enum):
    OFFICE = "office"
    EMERGENCY_DEPARTMENT = "emergency_department"
    INPATIENT_UNIT = "inpatient_unit"
    INTENSIVE_CARE_UNIT = "intensive_care_unit"
    HOME = "home"


class OrderCategory(Enum):
    LABORATORY = "laboratory"
    IMAGING = "imaging"
    MEDICATION = "medication"
    PROCEDURE = "procedure"
    CONSULTATION = "consultation"
    PHYSICAL_EXAMINATION = "physical_examination"
    NURSING = "nursing"
    COUNSELING = "counseling"
    DIET = "diet"


@dataclass
class CatalogEntry:
    """An entry in the clinical order catalog."""
    canonical_name: str
    category: str
    aliases: list[str]
    processing_time_minutes: int
    available_locations: list[str]
    result_template: str = ""


@dataclass
class PlacedOrder:
    """An order that has been placed during simulation."""
    raw_text: str
    canonical_name: str
    category: str
    placed_at: int
    report_at: int
    location: str
    result: Optional[str] = None
    delivered: bool = False


@dataclass
class SimEvent:
    """A conditional event in the case timeline."""
    trigger_time: int
    condition: Optional[dict]
    effects: dict
    narrative: str
    fired: bool = False


@dataclass
class PatientState:
    """Current state of the simulated patient."""
    vitals: dict[str, float] = field(default_factory=dict)
    active_medications: list[str] = field(default_factory=list)
    pending_orders: list[dict] = field(default_factory=list)
    completed_orders: list[dict] = field(default_factory=list)
    location: str = "emergency_department"
    current_time: int = 0
    narrative_log: list[dict] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)


@dataclass
class RubricItem:
    """A single item in the scoring rubric."""
    action: str
    category: str  # "required", "recommended", "contraindicated"
    max_credit: float
    time_window_start: int
    time_window_end: int
    prerequisites: list[str] = field(default_factory=list)
    decay_per_minute: float = 0.0
    risk_weight: float = 0.0


@dataclass
class TranscriptEntry:
    """A single entry in the simulation transcript."""
    action_type: str  # "order", "advance_clock", "change_location"
    timestamp: int
    details: dict = field(default_factory=dict)
