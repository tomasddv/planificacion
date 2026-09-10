"""Stable, pickle-compatible metadata for Streamlit cached data loaders."""
from dataclasses import dataclass


@dataclass(frozen=True)
class SourceInfo:
    label: str
    path: str | None
    modified: str | None
