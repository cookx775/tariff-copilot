from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

PENDING_NAVIGATION_KEY = "_pending_navigation"


def request_navigation(
    session_state: MutableMapping[str, Any], view: str, **identifiers: int
) -> None:
    """Stage a route change for the next full Streamlit script run."""
    session_state[PENDING_NAVIGATION_KEY] = {
        "view": view,
        **{name: str(value) for name, value in identifiers.items()},
    }


def resolve_route(
    session_state: MutableMapping[str, Any], query_params: Mapping[str, Any]
) -> dict[str, str]:
    """Resolve the route and atomically synchronize a staged route to the URL."""
    pending = session_state.pop(PENDING_NAVIGATION_KEY, None)
    if pending is not None:
        route = dict(pending)
        query_params.from_dict(route)  # type: ignore[attr-defined]
        return route
    return {name: str(value) for name, value in query_params.items()}
