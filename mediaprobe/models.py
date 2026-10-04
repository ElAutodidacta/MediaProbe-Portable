from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class DeviceInfo:
    mount: str
    label: str = ""
    filesystem: str = ""
    total_bytes: int = 0
    physical_bytes: Optional[int] = None
    free_bytes: int = 0
    disk_number: Optional[int] = None
    model: str = ""
    serial: str = ""
    bus_type: str = "Desconocido"
    bus_speed: str = "No expuesta por el sistema"
    usb_link_mbps: Optional[float] = None
    usb_version: str = ""
    vid: str = ""
    pid: str = ""
    controller: str = ""
    removable: bool = False
    system_disk: bool = False
    health: str = "No disponible"
    temperature_c: Optional[float] = None
    read_errors: Optional[int] = None
    write_errors: Optional[int] = None
    media_error_indicators: dict[str, int] = field(default_factory=dict)
    cid: str = ""
    csd: str = ""
    ocr: str = ""
    register_note: str = ""
    device_path: str = ""
    unique_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        parts = [self.mount]
        if self.label:
            parts.append(self.label)
        if self.model:
            parts.append(self.model)
        return " — ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResult:
    sequential_write_mbps: Optional[float] = None
    sequential_read_mbps: Optional[float] = None
    random_write_iops: Optional[float] = None
    random_read_iops: Optional[float] = None
    random_write_mbps: Optional[float] = None
    random_read_mbps: Optional[float] = None
    small_write_iops: Optional[float] = None
    small_read_iops: Optional[float] = None
    test_bytes: int = 0
    write_samples: list[dict[str, float]] = field(default_factory=list)
    sustained_write_mbps: Optional[float] = None
    sustained_min_mbps: Optional[float] = None
    sustained_p05_mbps: Optional[float] = None
    cache_drop_percent: Optional[float] = None
    cache_drop_at_bytes: Optional[int] = None
    sample_interval_bytes: int = 0
    mismatched_offsets: list[int] = field(default_factory=list)
    timed_out: bool = False
    disconnected: bool = False
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapacityResult:
    mode: str = "No ejecutada"
    requested_bytes: int = 0
    written_bytes: int = 0
    verified_bytes: int = 0
    mismatched_blocks: int = 0
    mismatched_offsets: list[dict[str, Any]] = field(default_factory=list)
    io_errors: list[str] = field(default_factory=list)
    complete_volume_coverage: bool = False
    integrity_ok: Optional[bool] = None
    elapsed_seconds: float = 0.0
    stopped: bool = False
    timed_out: bool = False
    disconnected: bool = False
    coverage_of_volume_percent: float = 0.0
    coverage_of_physical_percent: Optional[float] = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TechnicalAssessment:
    score: Optional[int] = None
    confidence: str = "Sin pruebas"
    sd_speed_class: str = "No determinada"
    application_class: str = "No determinada"
    fake_risk: str = "No determinado"
    verdict: str = "No evaluada"
    reader_bottleneck: str = "No determinado"
    claimed_class_results: list[dict[str, str]] = field(default_factory=list)
    estimated_fill_hours: Optional[float] = None
    recommendations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProbeReport:
    app_version: str
    created_at: str
    device: DeviceInfo
    benchmark: BenchmarkResult = field(default_factory=BenchmarkResult)
    capacity: CapacityResult = field(default_factory=CapacityResult)
    assessment: TechnicalAssessment = field(default_factory=TechnicalAssessment)
    session_errors: list[str] = field(default_factory=list)
    mode: str = "Inspección"
    declared_capacity_gb: Optional[float] = None
    claimed_classes: list[str] = field(default_factory=list)
    product: dict[str, Any] = field(default_factory=dict)
    online_lookup: dict[str, Any] = field(default_factory=dict)
    product_comparison: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 3,
            "app": {"name": "MediaProbe Portable", "version": self.app_version},
            "created_at": self.created_at,
            "device": self.device.to_dict(),
            "benchmark": self.benchmark.to_dict(),
            "capacity": self.capacity.to_dict(),
            "assessment": self.assessment.to_dict(),
            "session_errors": list(self.session_errors),
            "mode": self.mode,
            "declared_capacity_gb": self.declared_capacity_gb,
            "claimed_classes": list(self.claimed_classes),
            "product": dict(self.product),
            "online_lookup": dict(self.online_lookup),
            "product_comparison": list(self.product_comparison),
        }
