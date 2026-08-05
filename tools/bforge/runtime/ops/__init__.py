"""bforge operations. Importing this package registers every op.

Layering, low to high:

    session   scene lifecycle, inspection, transforms
    build     parametric primitives and mesh editing
    image     concept image -> production mesh (silhouette extrusion)
    material  PBR + procedural materials, baking
    uv        unwrapping and UV measurement
    paint     vertex colours, exported as glTF COLOR_0
    prop      finished props (crate, barrel, chest, rock, ...)
    kit       modular building kits on a snap grid
    env       terrain, trees, scatter
    char      humanoid blockouts, armatures, animation
    morph     shape keys, exported as glTF morph targets
    gameready LODs, collision, budgets, atlases
    ingest    retopo + transfer baking — the neural/scan finishing line
    render    contact sheets and turntables — the agent's eyes
    export    glTF/GLB with per-engine presets
    check     validation against the studio asset rules
"""

from . import session  # noqa: F401  (import order = registration order)
from . import build  # noqa: F401
from . import image  # noqa: F401
from . import arch  # noqa: F401
from . import material  # noqa: F401
from . import uv  # noqa: F401
from . import paint  # noqa: F401
from . import prop  # noqa: F401
from . import kit  # noqa: F401
from . import env  # noqa: F401
from . import char  # noqa: F401
from . import rig  # noqa: F401
from . import morph  # noqa: F401
from . import gameready  # noqa: F401
from . import ingest  # noqa: F401
from . import render  # noqa: F401
from . import export  # noqa: F401
from . import check  # noqa: F401
from . import meta  # noqa: F401
