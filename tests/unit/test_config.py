"""Unit tests for loserpoint.utils.config — the Phase 0 scaffold's one
piece of real logic, so `make test` proves the setup actually works end to end.
"""

from __future__ import annotations

import pytest
from loserpoint.utils.config import (
    DEFAULT_CONFIG_PATH,
    EmptyNetPolicyConfig,
    PanelConfig,
    load_config,
)


def test_load_default_config() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.seasons.modern_start == 2007
    assert config.panel.late_window_start_minute == 56
    assert config.empty_net_policy.default_mode == "exclude_pulled_and_empty_net"


def test_missing_config_file_raises_with_guidance(tmp_path) -> None:
    missing = tmp_path / "does_not_exist.yaml"
    with pytest.raises(FileNotFoundError, match="Config file not found"):
        load_config(missing)


def test_panel_config_rejects_inverted_late_window() -> None:
    with pytest.raises(ValueError, match="late window must satisfy"):
        PanelConfig(
            regulation_minutes=60,
            minute_boundary_convention="half_open_right",
            late_window_start_minute=58,
            late_window_end_minute=56,
            score_state_bins=("tied",),
            situation_filter="5v5",
        )


def test_panel_config_rejects_unknown_boundary_convention() -> None:
    with pytest.raises(ValueError, match="minute_boundary_convention"):
        PanelConfig(
            regulation_minutes=60,
            minute_boundary_convention="not_a_real_convention",
            late_window_start_minute=56,
            late_window_end_minute=60,
            score_state_bins=("tied",),
            situation_filter="5v5",
        )


def test_empty_net_policy_rejects_unknown_default_mode() -> None:
    with pytest.raises(ValueError, match="default_mode"):
        EmptyNetPolicyConfig(default_mode="bogus_mode", modes=("include_all",))
