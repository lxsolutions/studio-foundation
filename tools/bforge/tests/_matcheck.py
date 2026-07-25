import sys

sys.path.insert(0, "tools/bforge")
from bforge import Forge

f = Forge(workdir=".", out_dir="assets-generated/bforge")
try:
    f.start()
    f.call("session.reset")
    f.call(
        "session.import", path="assets-generated/bforge/chariot/colosseum_track.glb", _timeout=600
    )
    ml = f.call("material.list")
    for m in ml["materials"]:
        print(m["name"], m["users"], "gltf_safe" if m["gltf_safe"] else m["unsupported_nodes"])
finally:
    f.stop()
