"""Trust boundary and provenance rules for learning engine memory destinations.

Core rule: Nothing outside the user channel may ever write to user memory.
This closes persistent prompt injection.
"""
from __future__ import annotations

# Provenance sources
SOURCE_USER = "user"
SOURCE_CONFIRMED_ACTION = "confirmed_action"
SOURCE_INFERENCE = "inference"
SOURCE_FILE = "file"
SOURCE_WEB = "web"
SOURCE_TOOL = "tool"
SOURCE_ENV = "env"

ALL_SOURCES = {
    SOURCE_USER,
    SOURCE_CONFIRMED_ACTION,
    SOURCE_INFERENCE,
    SOURCE_FILE,
    SOURCE_WEB,
    SOURCE_TOOL,
    SOURCE_ENV,
}

# Trust boundary permissions matrix: (source_type, destination) -> allowed
# Destination targets: "user" (user memory), "project" (project memory), "domain" (domain knowledge)
_TRUST_MATRIX: dict[str, dict[str, bool]] = {
    SOURCE_USER: {
        "user": True,
        "project": True,
        "domain": True,
    },
    SOURCE_CONFIRMED_ACTION: {
        "user": True,
        "project": True,
        "domain": False,
    },
    SOURCE_INFERENCE: {
        "user": False,  # draft only
        "project": True,
        "domain": False,
    },
    SOURCE_FILE: {
        "user": False,
        "project": True,
        "domain": True,
    },
    SOURCE_WEB: {
        "user": False,
        "project": False,
        "domain": True,
    },
    SOURCE_TOOL: {
        "user": False,
        "project": False,
        "domain": True,
    },
    SOURCE_ENV: {
        "user": False,
        "project": False,
        "domain": False,
    },
}

_DESTINATION_ALIASES: dict[str, str] = {
    "user": "user",
    "user_memory": "user",
    "user_global": "user",
    "project": "project",
    "project_memory": "project",
    "domain": "domain",
    "domain_knowledge": "domain",
    "domain_memory": "domain",
}


def source_allowed(source_type: str, destination: str) -> bool:
    """Check if a signal from source_type is allowed to write to destination.

    Enforces the strict trust boundary matrix:
    - SOURCE_USER           -> user: True,  project: True,  domain: True
    - SOURCE_CONFIRMED_ACTION -> user: True,  project: True,  domain: False
    - SOURCE_INFERENCE      -> user: False, project: True,  domain: False
    - SOURCE_FILE           -> user: False, project: True,  domain: True
    - SOURCE_WEB            -> user: False, project: False, domain: True
    - SOURCE_TOOL           -> user: False, project: False, domain: True
    - SOURCE_ENV            -> all: False

    Core rule: Nothing outside the user channel may ever write to user memory.
    This closes persistent prompt injection.
    """
    src = str(source_type).strip().lower()
    dest_norm = str(destination).strip().lower()
    dest = _DESTINATION_ALIASES.get(dest_norm, dest_norm)

    allowed_destinations = _TRUST_MATRIX.get(src)
    if allowed_destinations is None:
        return False

    return allowed_destinations.get(dest, False)
