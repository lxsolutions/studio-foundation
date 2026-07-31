"""bforge operations. Importing this package registers every op.

Layering, low to high:

    session   scene lifecycle, inspection, transforms
    build     parametric primitives and mesh editing
    material  PBR + procedural materials, baking
    uv        unwrapping and UV measurement
    prop      finished props (crate, barrel, chest, rock, ...)
    kit       modular building kits on a snap grid
    env       terrain, trees, scatter
    char      humanoid blockouts, armatures, animation
    creature  quadruped and arthropod bases
    gameready LODs, collision, budgets, atlases
    render    contact sheets and turntables — the agent's eyes
    export    glTF/GLB with per-engine presets
    check     validation against the studio asset rules
"""

# Registration order is architectural: higher-level ops depend on namespaces
# imported above them. Alphabetical sorting would silently change the catalog.
# ruff: noqa: I001

from . import session  # noqa: F401  (import order = registration order)
from . import build  # noqa: F401
from . import arch  # noqa: F401
from . import material  # noqa: F401
from . import uv  # noqa: F401
from . import prop  # noqa: F401
from . import naval  # noqa: F401
from . import kit  # noqa: F401
from . import env  # noqa: F401
from . import char  # noqa: F401
from . import creature  # noqa: F401
from . import rig  # noqa: F401
from . import gameready  # noqa: F401
from . import render  # noqa: F401
from . import export  # noqa: F401
from . import check  # noqa: F401
from . import meta  # noqa: F401
