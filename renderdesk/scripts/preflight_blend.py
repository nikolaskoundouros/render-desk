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

    # Only two things can actually break a render by being absent: a linked library
    # the scene still uses, and an image that is neither packed nor on disk.
    #
    # blend_paths() reports far more than that. Appending data from another .blend
    # leaves its path behind on local datablocks, and those paths are residue: the
    # data is already in the file. Blocking on them refuses a perfectly good scene,
    # which is exactly what happened to a file with 2195 objects and no libraries
    # at all.
    missing, stale, residue = [], [], []
    libraries = {}
    for lib in bpy.data.libraries:
        target = bpy.path.abspath(lib.filepath)
        libraries[lib.filepath] = lib.users
        if target and not os.path.exists(target):
            (missing if lib.users else stale).append(lib.filepath)

    for image in bpy.data.images:
        if image.packed_file or not image.filepath or image.source == "GENERATED":
            continue
        if not image.users:
            continue
        target = bpy.path.abspath(image.filepath)
        if target and not os.path.exists(target):
            missing.append(image.filepath)

    known = set(missing) | set(stale)
    for path in bpy.utils.blend_paths(absolute=False, packed=False, local=False):
        if path and path not in known and not os.path.exists(bpy.path.abspath(path)):
            residue.append(path)

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
        "residue_paths": sorted(set(residue)),
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
