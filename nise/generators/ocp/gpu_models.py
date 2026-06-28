"""GPU model catalog for OCP report generation.

This catalog mirrors the hardware specifications defined in
ros-ocp-backend/internal/engine/gpu_catalog.yaml so that nise generates
data with correct DCGM-reported model names, frame buffer sizes, and
MIG profile geometries.

Maintenance: when ros-ocp-backend adds a new GPU model, add a matching
entry here so generated test data exercises the new model path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MIGProfile:
    """A single MIG partition geometry."""

    name: str  # e.g. "1g.10gb", "3g.40gb"
    slices: int  # GPU slices consumed (1, 2, 3, 4, 7)
    fb_size_mib: int  # frame buffer for this partition in MiB


@dataclass(frozen=True)
class GPUModel:
    """Hardware specification for one NVIDIA GPU model."""

    dcgm_name: str  # DCGM-reported string, e.g. "NVIDIA A100-SXM4-80GB"
    catalog_key: str  # ros-ocp-backend catalog key, e.g. "A100_80GB"
    fb_total_mib: int  # total frame buffer in MiB
    sm_count: int  # streaming multiprocessor count
    mig_supported: bool = False
    profiling_supported: bool = True
    profiles: tuple[MIGProfile, ...] = ()

    @property
    def fb_total_gib(self) -> float:
        return self.fb_total_mib / 1024.0


# ---------------------------------------------------------------------------
# Catalog — one entry per model variant, keyed by DCGM name.
# Sourced from ros-ocp-backend/internal/engine/gpu_catalog.yaml
# ---------------------------------------------------------------------------

GPU_CATALOG: dict[str, GPUModel] = {}


def _register(*models: GPUModel) -> None:
    for m in models:
        GPU_CATALOG[m.dcgm_name] = m


_register(
    GPUModel(
        dcgm_name="Tesla T4",
        catalog_key="T4",
        fb_total_mib=16384,
        sm_count=40,
    ),
    GPUModel(
        dcgm_name="NVIDIA A10",
        catalog_key="A10",
        fb_total_mib=24576,
        sm_count=72,
    ),
    GPUModel(
        dcgm_name="NVIDIA A10G",
        catalog_key="A10G",
        fb_total_mib=24576,
        sm_count=80,
    ),
    GPUModel(
        dcgm_name="NVIDIA A30-24GB",
        catalog_key="A30",
        fb_total_mib=24576,
        sm_count=56,
        mig_supported=True,
        profiles=(
            MIGProfile("1g.6gb", 1, 6144),
            MIGProfile("2g.12gb", 2, 12288),
            MIGProfile("4g.24gb", 4, 24576),
        ),
    ),
    GPUModel(
        dcgm_name="NVIDIA A100-PCIE-40GB",
        catalog_key="A100_40GB",
        fb_total_mib=40960,
        sm_count=108,
        mig_supported=True,
        profiles=(
            MIGProfile("1g.5gb", 1, 5120),
            MIGProfile("1g.10gb", 1, 10240),
            MIGProfile("2g.10gb", 2, 10240),
            MIGProfile("3g.20gb", 3, 20480),
            MIGProfile("4g.20gb", 4, 20480),
            MIGProfile("7g.40gb", 7, 40960),
        ),
    ),
    GPUModel(
        dcgm_name="NVIDIA A100-SXM4-80GB",
        catalog_key="A100_80GB",
        fb_total_mib=81920,
        sm_count=108,
        mig_supported=True,
        profiles=(
            MIGProfile("1g.10gb", 1, 10240),
            MIGProfile("1g.20gb", 1, 20480),
            MIGProfile("2g.20gb", 2, 20480),
            MIGProfile("3g.40gb", 3, 40960),
            MIGProfile("4g.40gb", 4, 40960),
            MIGProfile("7g.80gb", 7, 81920),
        ),
    ),
    GPUModel(
        dcgm_name="NVIDIA L4",
        catalog_key="L4",
        fb_total_mib=24576,
        sm_count=60,
    ),
    GPUModel(
        dcgm_name="NVIDIA L40",
        catalog_key="L40",
        fb_total_mib=49152,
        sm_count=142,
    ),
    GPUModel(
        dcgm_name="NVIDIA L40S",
        catalog_key="L40S",
        fb_total_mib=49152,
        sm_count=142,
    ),
    GPUModel(
        dcgm_name="NVIDIA H100-SXM5-80GB",
        catalog_key="H100_80GB",
        fb_total_mib=81920,
        sm_count=132,
        mig_supported=True,
        profiles=(
            MIGProfile("1g.10gb", 1, 10240),
            MIGProfile("1g.20gb", 1, 20480),
            MIGProfile("2g.20gb", 2, 20480),
            MIGProfile("3g.40gb", 3, 40960),
            MIGProfile("4g.40gb", 4, 40960),
            MIGProfile("7g.80gb", 7, 81920),
        ),
    ),
    GPUModel(
        dcgm_name="NVIDIA H100 NVL",
        catalog_key="H100_94GB",
        fb_total_mib=96256,
        sm_count=132,
        mig_supported=True,
        profiles=(
            MIGProfile("1g.12gb", 1, 12288),
            MIGProfile("1g.24gb", 1, 24576),
            MIGProfile("2g.24gb", 2, 24576),
            MIGProfile("3g.47gb", 3, 48128),
            MIGProfile("4g.47gb", 4, 48128),
            MIGProfile("7g.94gb", 7, 96256),
        ),
    ),
    GPUModel(
        dcgm_name="NVIDIA H200",
        catalog_key="H200_141GB",
        fb_total_mib=144384,
        sm_count=132,
        mig_supported=True,
        profiles=(
            MIGProfile("1g.18gb", 1, 18432),
            MIGProfile("1g.35gb", 1, 35840),
            MIGProfile("2g.35gb", 2, 35840),
            MIGProfile("3g.71gb", 3, 72704),
            MIGProfile("4g.71gb", 4, 72704),
            MIGProfile("7g.141gb", 7, 144384),
        ),
    ),
    GPUModel(
        dcgm_name="NVIDIA B200",
        catalog_key="B200_180GB",
        fb_total_mib=184320,
        sm_count=160,
        mig_supported=True,
        profiles=(
            MIGProfile("1g.23gb", 1, 23552),
            MIGProfile("1g.45gb", 1, 46080),
            MIGProfile("2g.45gb", 2, 46080),
            MIGProfile("3g.90gb", 3, 92160),
            MIGProfile("4g.90gb", 4, 92160),
            MIGProfile("7g.180gb", 7, 184320),
        ),
    ),
    GPUModel(
        dcgm_name="Tesla V100-SXM2-16GB",
        catalog_key="V100_16GB",
        fb_total_mib=16384,
        sm_count=80,
        profiling_supported=False,
    ),
    GPUModel(
        dcgm_name="Tesla V100-SXM2-32GB",
        catalog_key="V100_32GB",
        fb_total_mib=32768,
        sm_count=80,
        profiling_supported=False,
    ),
    GPUModel(
        dcgm_name="Tesla P100-SXM2-16GB",
        catalog_key="P100",
        fb_total_mib=16384,
        sm_count=56,
        profiling_supported=False,
    ),
    GPUModel(
        dcgm_name="Tesla P40",
        catalog_key="P40",
        fb_total_mib=24576,
        sm_count=30,
        profiling_supported=False,
    ),
)


# ---------------------------------------------------------------------------
# Convenience helpers used by the OCP generator
# ---------------------------------------------------------------------------

_LEGACY_NAME_MAP: dict[str, str] = {
    "A100": "NVIDIA A100-SXM4-80GB",
    "A30": "NVIDIA A30-24GB",
    "H100": "NVIDIA H100-SXM5-80GB",
    "V100": "Tesla V100-SXM2-32GB",
    "T4": "Tesla T4",
    "Tesla T4": "Tesla T4",
    "L40S": "NVIDIA L40S",
    "L40": "NVIDIA L40",
    "L4": "NVIDIA L4",
    "A10": "NVIDIA A10",
    "A10G": "NVIDIA A10G",
    "P100": "Tesla P100-SXM2-16GB",
    "P40": "Tesla P40",
}


def _resolve_legacy_name(name: str) -> GPUModel | None:
    """Resolve a legacy short name to a GPUModel, or None."""
    dcgm = _LEGACY_NAME_MAP.get(name)
    return GPU_CATALOG.get(dcgm) if dcgm else None


def get_all_dcgm_names() -> tuple[str, ...]:
    """DCGM name strings for all models in the catalog."""
    return tuple(GPU_CATALOG.keys())


def get_fb_total_mib(dcgm_name: str) -> int:
    """Frame buffer size in MiB for a given DCGM model name.

    Handles both full DCGM names and legacy short names.
    Falls back to 15360 (T4) for unknown models to match prior behaviour.
    """
    model = GPU_CATALOG.get(dcgm_name) or _resolve_legacy_name(dcgm_name)
    return model.fb_total_mib if model else 15360


def supports_profiling(dcgm_name: str) -> bool:
    """Whether the GPU supports DCGM PROF_ profiling metrics.

    Handles both full DCGM names ("NVIDIA A100-SXM4-80GB") and legacy
    short names ("A100") from static YAML configs.
    """
    model = GPU_CATALOG.get(dcgm_name)
    if model is not None:
        return model.profiling_supported
    model = _resolve_legacy_name(dcgm_name)
    return model.profiling_supported if model else False


def supports_mig(dcgm_name: str) -> bool:
    """Whether the GPU supports Multi-Instance GPU (MIG)."""
    model = GPU_CATALOG.get(dcgm_name)
    return model.mig_supported if model else False


def get_mig_profiles(dcgm_name: str) -> tuple[MIGProfile, ...]:
    """MIG profiles available for a model (empty tuple if not MIG-capable)."""
    model = GPU_CATALOG.get(dcgm_name)
    return model.profiles if model else ()


# Default subset used for random GPU generation (datacenter-class GPUs).
# Excludes older/less common models like P100, P40, V100-16GB.
DEFAULT_GPU_MODELS: tuple[str, ...] = (
    "Tesla T4",
    "NVIDIA A100-SXM4-80GB",
    "Tesla V100-SXM2-32GB",
    "NVIDIA H100-SXM5-80GB",
    "NVIDIA A30-24GB",
    "NVIDIA L40S",
    "NVIDIA A10",
    "NVIDIA A10G",
)

# MIG-capable models from DEFAULT_GPU_MODELS
MIG_CAPABLE_MODELS: tuple[str, ...] = tuple(name for name in DEFAULT_GPU_MODELS if supports_mig(name))
