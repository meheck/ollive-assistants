"""Personal assistant backends (OSS + frontier) sharing one interface."""

from .base import Assistant, Message, ShortTermMemory

__all__ = ["Assistant", "Message", "ShortTermMemory"]
