"""bforge — a headless, deterministic Blender asset forge for game development.

Host-side package (never imports bpy). The Blender-side runtime lives in
``tools/bforge/runtime``.
"""

from .client import DaemonError, Forge, ForgeError, find_blender

__all__ = ["Forge", "ForgeError", "DaemonError", "find_blender"]
__version__ = "0.1.0"
