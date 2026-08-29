"""Typed task brief definitions for proactive intelligence routing and constraint modeling."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class TaskType(str, Enum):
    """Categorized task intent derived from user input and context."""
    DIRECT_ANSWER = "direct_answer"               # Explanations, static knowledge, greetings
    SELF_KNOWLEDGE = "self_knowledge"             # Stable product & command knowledge, slash commands, UI capabilities
    CURRENT_STATE = "current_state"               # Active skills, models, session metrics from typed providers (zero repo tools)
    SYSTEM_INSPECTION = "system_inspection"       # Hardware, OS, RAM, disk, environment facts
    RECOMMENDATION = "recommendation"             # Local model fit, hardware fit, tool choices
    LOCAL_CODE_INSPECTION = "code_inspection"     # Reading/searching workspace code
    LOCAL_CODE_MODIFICATION = "code_modification" # Editing/creating workspace files
    WEB_RESEARCH = "web_research"                 # Time-sensitive facts, latest releases, external docs
    DIAGNOSIS = "diagnosis"                       # Health checks, doctor, troubleshooting
    CLARIFICATION_NEEDED = "clarification_needed" # Ambiguous request where safe discovery is impossible
    SKILL_AUTHORING = "skill_authoring"           # On-demand skill creation and fast publication gate


class ResponseFormat(str, Enum):
    """Target presentation structure for response rendering."""
    PROSE = "prose"   # 1-4 lines natural prose (default)
    LIST = "list"     # Bulleted/numbered list (only for >=3 items or sequential steps)
    TABLE = "table"   # Markdown table (only for multi-entity comparisons)
    CODE = "code"     # Prose introduction + fenced code snippet


@dataclass(frozen=True)
class TaskBrief:
    """Immutable structured brief representing inferred task requirements and constraints."""
    task_type: TaskType
    requested_outcome: str
    confidence: float                             # 0.0 to 1.0 confidence score
    scope: Literal["system", "workspace", "general", "external"]
    needs_environment_facts: bool = False
    environment_freshness: Literal["session_static", "dynamic_refresh", "none"] = "none"
    needs_workspace_context: bool = False
    needs_web_research: bool = False
    requires_disk_vram_separation: bool = False
    preferred_format: ResponseFormat = ResponseFormat.PROSE
    show_code: bool = False
    requires_uncertainty_disclosure: bool = False
    relevant_command: str | None = None
