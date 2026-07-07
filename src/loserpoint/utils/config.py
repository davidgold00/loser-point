"""Typed loader for config/config.yaml.

Every analytic parameter in the project (season ranges, panel window
boundaries, empty-net policy, etc.) lives in config.yaml, not scattered
through source files. This module is the single place that parses it into
validated dataclasses so a typo in the YAML fails fast at load time rather
than silently downstream.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "config.yaml"

VALID_EMPTY_NET_MODES = frozenset(
    {"exclude_pulled_and_empty_net", "exclude_final_two_minutes", "include_all"}
)
VALID_BOUNDARY_CONVENTIONS = frozenset({"half_open_right", "half_open_left"})


@dataclass(frozen=True)
class SeasonsConfig:
    modern_start: int
    modern_end: int
    historical_start: int
    historical_end: int


@dataclass(frozen=True)
class PanelConfig:
    regulation_minutes: int
    minute_boundary_convention: str
    late_window_start_minute: int
    late_window_end_minute: int
    score_state_bins: tuple[str, ...]
    situation_filter: str

    def __post_init__(self) -> None:
        if self.minute_boundary_convention not in VALID_BOUNDARY_CONVENTIONS:
            raise ValueError(
                f"panel.minute_boundary_convention={self.minute_boundary_convention!r} "
                f"must be one of {sorted(VALID_BOUNDARY_CONVENTIONS)}"
            )
        if not (
            1
            <= self.late_window_start_minute
            <= self.late_window_end_minute
            <= self.regulation_minutes
        ):
            raise ValueError(
                "panel late window must satisfy "
                "1 <= late_window_start_minute <= late_window_end_minute "
                f"<= regulation_minutes; got {self.late_window_start_minute}, "
                f"{self.late_window_end_minute}, {self.regulation_minutes}"
            )


@dataclass(frozen=True)
class EmptyNetPolicyConfig:
    default_mode: str
    modes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.default_mode not in VALID_EMPTY_NET_MODES:
            raise ValueError(
                f"empty_net_policy.default_mode={self.default_mode!r} "
                f"must be one of {sorted(VALID_EMPTY_NET_MODES)}"
            )
        unknown = set(self.modes) - VALID_EMPTY_NET_MODES
        if unknown:
            raise ValueError(f"empty_net_policy.modes has unknown entries: {sorted(unknown)}")


@dataclass(frozen=True)
class ValidationConfig:
    reconciliation_sample_games_per_season: int
    hard_failure_mismatch_threshold: float


@dataclass(frozen=True)
class Config:
    seasons: SeasonsConfig
    rule_change_dates: dict[str, str]
    panel: PanelConfig
    empty_net_policy: EmptyNetPolicyConfig
    validation: ValidationConfig
    scraping: dict[str, dict]
    models: dict


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    """Load and validate config.yaml into a typed `Config`.

    Args:
        path: Location of the YAML file. Defaults to `config/config.yaml`
            at the repo root.

    Returns:
        A validated `Config` instance.

    Raises:
        FileNotFoundError: if `path` does not exist.
        ValueError: if a required field is missing or fails validation
            (e.g. an unknown empty-net mode, or an inverted late window).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found at {path}. Expected the repo's "
            "config/config.yaml — check your working directory or pass "
            "an explicit path."
        )
    raw = yaml.safe_load(path.read_text())

    try:
        seasons = SeasonsConfig(**raw["seasons"])
        panel = PanelConfig(
            **{**raw["panel"], "score_state_bins": tuple(raw["panel"]["score_state_bins"])}
        )
        empty_net_policy = EmptyNetPolicyConfig(
            default_mode=raw["empty_net_policy"]["default_mode"],
            modes=tuple(raw["empty_net_policy"]["modes"]),
        )
        validation = ValidationConfig(**raw["validation"])
    except KeyError as exc:
        raise ValueError(f"config.yaml is missing required key: {exc}") from exc

    return Config(
        seasons=seasons,
        rule_change_dates=raw["rule_change_dates"],
        panel=panel,
        empty_net_policy=empty_net_policy,
        validation=validation,
        scraping=raw["scraping"],
        models=raw["models"],
    )
