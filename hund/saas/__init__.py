"""SaaS — chat bridge between Stydes dashboard and Hund.ai intelligence."""
from .chat import saas_chat
from .prompt import build_saas_prompt

__all__ = ["saas_chat", "build_saas_prompt"]
