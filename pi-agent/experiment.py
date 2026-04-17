"""
Experiment-mode helpers shared across Pi agent modules.
"""

from __future__ import annotations

import uuid

EXPERIMENT_MODES = (
    "single_link_wifi",
    "single_link_lte",
    "adaptive",
    "redundant",
)

DECISION_REASONS = (
    "baseline",
    "adaptive_score",
    "adaptive_link_down",
    "adaptive_hold",
    "redundant",
)

LEGACY_MODE_MAP = {
    "wifi_only": "single_link_wifi",
    "lte_only": "single_link_lte",
    "auto": "adaptive",
}


def normalize_experiment_mode(mode: str) -> str:
    return LEGACY_MODE_MAP.get(mode, mode)


def new_experiment_session_id() -> str:
    return uuid.uuid4().hex
