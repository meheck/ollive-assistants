"""Personal assistant backends (OSS + frontier) sharing one interface."""

from .base import Assistant, Message, ShortTermMemory

__all__ = [
    "Assistant",
    "Message",
    "ShortTermMemory",
    "OSSAssistant",
    "FrontierAssistant",
]


def __getattr__(name: str):
    # Lazy re-export so importing the package doesn't pull torch (OSS) or the
    # Gemini SDK (frontier) unless that backend is actually used.
    if name == "OSSAssistant":
        from .oss import OSSAssistant

        return OSSAssistant
    if name == "FrontierAssistant":
        from .frontier import FrontierAssistant

        return FrontierAssistant
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
