"""Runs inside Blender: report everything that decides whether this job can render.

Usage: blender -b file.blend --factory-startup -noaudio --python preflight_blend.py -- out.json
"""
import json
import os
import sys

import bpy


def main(out_path):
    scene = bpy.context.scene
    render = scene.render

    # A linked library that nothing actually uses is a leftover, not a problem. The
    # scene renders fine without it, so blocking on one would refuse a good file.
    missing, stale = [], []
    libraries = {}
    for lib in bpy.data.libraries:
        target = bpy.path.abspath(lib.filepath)
        users = getattr(lib, "users_id", None)
        count = len(users) if users is not None else -1
        libraries[lib.filepath] = count
        if target and not os.path.exists(target):
            (missing if count != 0 else stale).append(lib.filepath)

    for path in bpy.utils.blend_paths(absolute=True, packed=False, local=False):
        if not path or path in libraries:
            continue
        if not os.path.exists(bpy.path.abspath(path)):
            missing.append(path)

    report = {
        "blender_running": list(bpy.app.version),
        "blender_saved_with": list(bpy.data.version),
        "engine": render.engine,
        "camera": scene.camera.name if scene.camera else None,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_step": scene.frame_step,
        "fps": round(render.fps / render.fps_base, 4),
        "resolution": [
            int(render.resolution_x * render.resolution_percentage / 100),
            int(render.resolution_y * render.resolution_percentage / 100),
        ],
        "resolution_percentage": render.resolution_percentage,
        "missing_files": sorted(set(missing)),
        "stale_links": sorted(set(stale)),
        "libraries": {k: v for k, v in sorted(libraries.items())},
        "objects": len(scene.objects),
        "packed_images": sum(1 for i in bpy.data.images if i.packed_file),
    }
    try:
        report["samples"] = scene.cycles.samples
    except AttributeError:
        report["samples"] = None
    report["frames"] = len(range(scene.frame_start, scene.frame_end + 1, max(1, scene.frame_step)))

    with open(out_path, "w") as fh:
        json.dump(report, fh, indent=2)


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1])
