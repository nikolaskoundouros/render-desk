"""Runs inside Blender: render the open .blend to a numbered PNG sequence.

Usage:
  blender -b file.blend --factory-startup -noaudio --python render_job.py -- \
      --out DIR [--device OPTIX|CUDA|METAL|NONE] [--samples N] [--scale PCT]

One frame per bpy.ops call so a killed render resumes instead of restarting:
frames already on disk are skipped. Progress goes to stdout as RD_ lines for the
broker to read.
"""
import argparse
import os
import sys
import time

import bpy


def enable_gpu(device):
    if device in ("", "NONE", "CPU"):
        bpy.context.scene.cycles.device = "CPU"
        return {"device": "CPU", "gpus": []}
    prefs = bpy.context.preferences.addons["cycles"].preferences
    try:
        prefs.compute_device_type = device
    except TypeError as exc:
        raise SystemExit(f"RD_ERROR this Blender does not support device {device}: {exc}")
    refresh = getattr(prefs, "refresh_devices", None) or getattr(prefs, "get_devices")
    refresh()
    used = []
    for dev in prefs.devices:
        dev.use = dev.type == device
        if dev.use:
            used.append(dev.name)
    if not used:
        raise SystemExit(f"RD_ERROR no {device} device found on this machine")
    bpy.context.scene.cycles.device = "GPU"
    return {"device": device, "gpus": used}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--device", default="NONE")
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--scale", type=int, default=0)
    args = ap.parse_args(argv)

    scene = bpy.context.scene
    render = scene.render
    os.makedirs(args.out, exist_ok=True)

    if render.engine == "CYCLES":
        info = enable_gpu(args.device)
        print(f"RD_DEVICE {info['device']} {', '.join(info['gpus']) or 'cpu'}", flush=True)
        if args.samples:
            scene.cycles.samples = min(scene.cycles.samples, args.samples)
    else:
        print(f"RD_DEVICE engine {render.engine} uses its own device", flush=True)
    if args.scale:
        render.resolution_percentage = args.scale

    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGB"
    render.film_transparent = render.film_transparent

    frames = list(range(scene.frame_start, scene.frame_end + 1, max(1, scene.frame_step)))
    print(f"RD_PLAN {len(frames)} frames {frames[0]}-{frames[-1]} "
          f"{int(render.resolution_x * render.resolution_percentage / 100)}x"
          f"{int(render.resolution_y * render.resolution_percentage / 100)}", flush=True)

    done = 0
    for frame in frames:
        target = os.path.join(args.out, f"frame_{frame:05d}.png")
        done += 1
        if os.path.exists(target) and os.path.getsize(target) > 0:
            print(f"RD_FRAME {done}/{len(frames)} {frame} skipped", flush=True)
            continue
        started = time.time()
        scene.frame_set(frame)
        render.filepath = target
        bpy.ops.render.render(write_still=True)
        print(f"RD_FRAME {done}/{len(frames)} {frame} ok {time.time() - started:.1f}s", flush=True)
    print("RD_DONE", flush=True)


if __name__ == "__main__":
    main()
