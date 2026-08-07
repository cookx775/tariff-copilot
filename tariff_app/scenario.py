from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .models import ProvenanceRecord, ScenarioSeedSummary

SCENARIO_VERSION = "demonstration-2025-fy.v1"
MEASUREMENT_PERIOD = "FY2025 ending 2025-09-30"
PUBLIC_ENTERPRISE_SOURCE = ProvenanceRecord(
    label="Public source",
    source_name="Mueller Water Products FY2025 Form 10-K",
    source_url=(
        "https://www.sec.gov/Archives/edgar/data/1350593/000135059325000066/mwa-20250930.htm"
    ),
    source_citation="FY2025 Form 10-K, Item 1, Business.",
)
SYNTHETIC_SCENARIO_SOURCE = ProvenanceRecord(
    label="Synthetic demonstration data",
    source_name="Demonstration Scenario v1",
    source_url=None,
    source_citation="Synthetic procurement model; not Mueller Water Products data.",
)
SYNTHETIC_CLASSIFICATION_SOURCE = ProvenanceRecord(
    label="Synthetic demonstration data",
    source_name="Demonstration Scenario v1",
    source_url=None,
    source_citation="Synthetic classification assignment; validate before use.",
)


@dataclass(frozen=True)
class SegmentSeed:
    key: str
    name: str


@dataclass(frozen=True)
class ProductLineSeed:
    key: str
    name: str
    segment_key: str


@dataclass(frozen=True)
class ComponentSeed:
    key: str
    name: str


@dataclass(frozen=True)
class BomRelationshipSeed:
    product_line_key: str
    component_key: str


@dataclass(frozen=True)
class SupplierSeed:
    key: str
    name: str


@dataclass(frozen=True)
class CountrySeed:
    code: str
    name: str


@dataclass(frozen=True)
class SupplyRelationshipSeed:
    key: str
    component_key: str
    supplier_key: str
    country_code: str
    annual_spend: Decimal


@dataclass(frozen=True)
class ClassificationAssertionSeed:
    key: str
    component_key: str
    supply_relationship_key: str
    sourced_variant: str
    jurisdiction: str
    schedule_period: str
    hts_code: str
    state: str


@dataclass(frozen=True)
class DemonstrationScenario:
    segments: tuple[SegmentSeed, ...]
    product_lines: tuple[ProductLineSeed, ...]
    components: tuple[ComponentSeed, ...]
    bom_relationships: tuple[BomRelationshipSeed, ...]
    suppliers: tuple[SupplierSeed, ...]
    countries: tuple[CountrySeed, ...]
    supply_relationships: tuple[SupplyRelationshipSeed, ...]
    classification_assertions: tuple[ClassificationAssertionSeed, ...]

    def summary(self) -> ScenarioSeedSummary:
        return ScenarioSeedSummary(
            scenario_version=SCENARIO_VERSION,
            segment_count=len(self.segments),
            product_line_count=len(self.product_lines),
            component_count=len(self.components),
            bom_relationship_count=len(self.bom_relationships),
            supplier_count=len(self.suppliers),
            supply_relationship_count=len(self.supply_relationships),
            country_count=len(self.countries),
            classification_assertion_count=len(self.classification_assertions),
            annual_spend=sum(
                (relationship.annual_spend for relationship in self.supply_relationships),
                Decimal("0.00"),
            ),
        )


DEMONSTRATION_SCENARIO = DemonstrationScenario(
    segments=(
        SegmentSeed("water_flow_solutions", "Water Flow Solutions"),
        SegmentSeed("water_management_solutions", "Water Management Solutions"),
    ),
    product_lines=(
        ProductLineSeed("specialty_valves", "Specialty Valves", "water_flow_solutions"),
        ProductLineSeed("repair_products", "Repair Products", "water_management_solutions"),
        ProductLineSeed("fire_hydrants", "Fire Hydrants", "water_management_solutions"),
    ),
    components=(
        ComponentSeed("valve_body_trim", "Valve body and trim assembly"),
        ComponentSeed("check_valve_cartridge", "Check-valve cartridge"),
        ComponentSeed("ductile_iron_repair_coupling", "Ductile-iron grooved repair coupling"),
        ComponentSeed("brass_service_fitting", "Brass service fitting"),
        ComponentSeed("hydrant_o_ring_seal_kit", "Hydrant O-ring seal kit"),
    ),
    bom_relationships=(
        BomRelationshipSeed("specialty_valves", "valve_body_trim"),
        BomRelationshipSeed("specialty_valves", "check_valve_cartridge"),
        BomRelationshipSeed("specialty_valves", "brass_service_fitting"),
        BomRelationshipSeed("repair_products", "ductile_iron_repair_coupling"),
        BomRelationshipSeed("fire_hydrants", "valve_body_trim"),
        BomRelationshipSeed("fire_hydrants", "hydrant_o_ring_seal_kit"),
    ),
    suppliers=(
        SupplierSeed("scenario_supplier_cn_01", "Scenario Supplier CN-01"),
        SupplierSeed("scenario_supplier_us_01", "Scenario Supplier US-01"),
        SupplierSeed("scenario_supplier_mx_01", "Scenario Supplier MX-01"),
        SupplierSeed("scenario_supplier_ca_01", "Scenario Supplier CA-01"),
        SupplierSeed("scenario_supplier_us_02", "Scenario Supplier US-02"),
    ),
    countries=(
        CountrySeed("CN", "China"),
        CountrySeed("US", "United States"),
        CountrySeed("MX", "Mexico"),
        CountrySeed("CA", "Canada"),
    ),
    supply_relationships=(
        SupplyRelationshipSeed(
            "valve_body_trim_cn_01",
            "valve_body_trim",
            "scenario_supplier_cn_01",
            "CN",
            Decimal("6000000.00"),
        ),
        SupplyRelationshipSeed(
            "valve_body_trim_us_01",
            "valve_body_trim",
            "scenario_supplier_us_01",
            "US",
            Decimal("2000000.00"),
        ),
        SupplyRelationshipSeed(
            "check_valve_cartridge_cn_01",
            "check_valve_cartridge",
            "scenario_supplier_cn_01",
            "CN",
            Decimal("3000000.00"),
        ),
        SupplyRelationshipSeed(
            "ductile_iron_repair_coupling_mx_01",
            "ductile_iron_repair_coupling",
            "scenario_supplier_mx_01",
            "MX",
            Decimal("5000000.00"),
        ),
        SupplyRelationshipSeed(
            "brass_service_fitting_ca_01",
            "brass_service_fitting",
            "scenario_supplier_ca_01",
            "CA",
            Decimal("4000000.00"),
        ),
        SupplyRelationshipSeed(
            "hydrant_o_ring_seal_kit_us_02",
            "hydrant_o_ring_seal_kit",
            "scenario_supplier_us_02",
            "US",
            Decimal("4000000.00"),
        ),
    ),
    classification_assertions=(
        ClassificationAssertionSeed(
            "valve_body_trim_cn_validated",
            "valve_body_trim",
            "valve_body_trim_cn_01",
            "primary-cn-01",
            "US",
            "2025-09-30",
            "8481.90.90.20",
            "validated",
        ),
        ClassificationAssertionSeed(
            "valve_body_trim_us_validated",
            "valve_body_trim",
            "valve_body_trim_us_01",
            "secondary-us-01",
            "US",
            "2025-09-30",
            "8481.90.90.20",
            "validated",
        ),
        ClassificationAssertionSeed(
            "valve_body_trim_cn_superseded",
            "valve_body_trim",
            "valve_body_trim_cn_01",
            "primary-cn-01",
            "US",
            "2024-09-30",
            "8481.90.90",
            "superseded",
        ),
        ClassificationAssertionSeed(
            "check_valve_cartridge_candidate_copper",
            "check_valve_cartridge",
            "check_valve_cartridge_cn_01",
            "unconfirmed-copper",
            "US",
            "2025-09-30",
            "8481.30.10",
            "candidate",
        ),
        ClassificationAssertionSeed(
            "check_valve_cartridge_candidate_iron_steel",
            "check_valve_cartridge",
            "check_valve_cartridge_cn_01",
            "unconfirmed-iron-steel",
            "US",
            "2025-09-30",
            "8481.30.20",
            "candidate",
        ),
        ClassificationAssertionSeed(
            "ductile_iron_repair_coupling_validated",
            "ductile_iron_repair_coupling",
            "ductile_iron_repair_coupling_mx_01",
            "primary-mx-01",
            "US",
            "2025-09-30",
            "7307.19.30.40",
            "validated",
        ),
        ClassificationAssertionSeed(
            "brass_service_fitting_validated",
            "brass_service_fitting",
            "brass_service_fitting_ca_01",
            "primary-ca-01",
            "US",
            "2025-09-30",
            "7412.20.00.85",
            "validated",
        ),
        ClassificationAssertionSeed(
            "hydrant_o_ring_seal_kit_validated",
            "hydrant_o_ring_seal_kit",
            "hydrant_o_ring_seal_kit_us_02",
            "primary-us-02",
            "US",
            "2025-09-30",
            "4016.93.50.10",
            "validated",
        ),
    ),
)
