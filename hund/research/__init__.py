"""Research — domain knowledge scope estimation and progress tracking."""
from .agent import research_domain
from .scope import KnowledgeScope, calculate_progress

__all__ = ["research_domain", "KnowledgeScope", "calculate_progress"]
