"""
Video Note Generator V2 / 红笔

A modular video note generation tool with multi-platform support
"""

__version__ = "0.1.0"
__author__ = "Hongbi"
__email__ = "grow8org@gmail.com"

from .config import get_settings, Settings

__all__ = [
    "get_settings",
    "Settings",
]
