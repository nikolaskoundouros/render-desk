# A live Blender on the workbench (Nick, 2026-10-07: "this all process is very inefficient"). One Blender opens the scene
# once and stays open; every change is a small Python job dropped into JOBS and run in the same session, so nothing is
# rebuilt and no file is reopened. Stills render inside the session. Before this, every one-line change rebuilt the whole
# scene through six scripts (~4 min) and reopened a 190 MB file for each still (~20 s each).
#   $BLENDER -b SCENE.blend --python scripts/bserve.py -- JOBS_DIR
# Jobs see these helpers: stills(scene, frames, outdir, width=540, samples=24, camera=None, mute=None),
# revert(path), save(path), run_script(path, *args), visible(obj, frames, scene), overlaps(a, b, frames, scene, gap).
import bpy, os, sys, time, glob, io, traceback, contextlib
from mathutils import Vector
from mathutils.bvhtree import BVHTree

JOBS = sys.argv[sys.argv.index('--') + 1]
os.makedirs(JOBS, exist_ok=True)

def _gpu():
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for kind in ('OPTIX', 'CUDA', 'METAL'):
        try: prefs.compute_device_type = kind; break
        except TypeError: continue
    prefs.get_devices()
    for d in prefs.devices: d.use = d.type != 'CPU'
_gpu()

def stills(scene, frames, outdir, width=540, samples=24, camera=None, mute=None):
    """Render frames of one scene into outdir/fNNNN.png; the scene's own settings are put back afterwards."""
    sc = bpy.data.scenes[scene]; bpy.context.window.scene = sc; os.makedirs(outdir, exist_ok=True)
    keep = (sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage, sc.render.filepath,
            sc.render.image_settings.file_format, sc.camera, getattr(sc.cycles, 'samples', None), getattr(sc.cycles, 'device', None))
    muted = []
    try:
        sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = width, round(width * 16 / 9), 100
        if sc.render.engine == 'CYCLES': sc.cycles.device = 'GPU'; sc.cycles.samples = samples; sc.cycles.use_denoising = True
        if camera: sc.camera = bpy.data.objects[camera]
        if mute and sc.sequence_editor:
            for st in (getattr(sc.sequence_editor, 'strips_all', None) or sc.sequence_editor.sequences_all):
                if st.name.startswith(mute) and not st.mute: st.mute = True; muted.append(st)
        sc.render.image_settings.file_format = 'PNG'
        t = time.time()
        for f in frames:
            sc.frame_set(f); sc.render.filepath = os.path.join(outdir, f'f{f:04d}.png'); bpy.ops.render.render(write_still=True, scene=sc.name)
        print(f'STILLS {scene} {len(frames)} frames in {time.time() - t:.1f}s -> {outdir}')
    finally:
        (sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage, sc.render.filepath,
         sc.render.image_settings.file_format, sc.camera) = keep[:6]
        if keep[6] is not None: sc.cycles.samples = keep[6]
        if keep[7] is not None: sc.cycles.device = keep[7]
        for st in muted: st.mute = False

def revert(path):
    """Throw away the session's changes and open path (the base a step starts from)."""
    bpy.ops.wm.open_mainfile(filepath=path); _gpu(); print('REVERTED to', path)

def save(path):
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=path, copy=True); print('SAVED', path)

def run_script(path, *args):
    """Run one of the project's build scripts inside the session, as if Blender had been started with it."""
    keep = sys.argv[:]
    sys.argv = [sys.argv[0], '--'] + [str(a) for a in args]
    try: exec(compile(open(path).read(), path, 'exec'), {'__name__': '__main__', '__file__': path, '_where': _where})
    finally: sys.argv = keep

def _world_tree(o, dg):
    ev = o.evaluated_get(dg); me = ev.to_mesh(); W = o.matrix_world
    tree = BVHTree.FromPolygons([W @ v.co for v in me.vertices], [tuple(p.vertices) for p in me.polygons]); ev.to_mesh_clear()
    return tree

def _where(o, dg):
    """World position of o; Follow Path is worked out here (this session does not apply it to the object)."""
    fp = next((c for c in o.constraints if c.type == 'FOLLOW_PATH' and c.target and c.use_fixed_location), None)
    if not fp: return o.evaluated_get(dg).matrix_world.translation.copy()
    cv = fp.target.evaluated_get(dg); me = cv.to_mesh(); W = fp.target.matrix_world
    pts = [W @ v.co for v in me.vertices]; cv.to_mesh_clear()
    seg = [(pts[i + 1] - pts[i]).length for i in range(len(pts) - 1)]; goal = fp.offset_factor * sum(seg); acc = 0.0
    for i, L in enumerate(seg):
        if acc + L >= goal: return pts[i].lerp(pts[i + 1], (goal - acc) / L if L else 0)
        acc += L
    return pts[-1]

def visible(obj, frames, scene):
    """For each frame: is obj's centre seen by the camera, and if not, what is in front of it (first opaque-looking hit)."""
    sc = bpy.data.scenes[scene]; bpy.context.window.scene = sc; out = []
    for f in frames:
        sc.frame_set(f); dg = bpy.context.evaluated_depsgraph_get(); o = sc.objects[obj]
        if o.hide_render: out.append((f, 'hidden')); continue
        cam = sc.camera.evaluated_get(dg).matrix_world.translation.copy(); tgt = _where(o, dg); d = (tgt - cam)   # evaluated: constraints applied
        hits = []; origin = cam.copy()
        for _ in range(12):
            r = sc.ray_cast(dg, origin, d.normalized(), distance=max(1e-4, (tgt - origin).length - 1e-4))
            if not r[0]: break
            hits.append(r[4].name); origin = r[1] + d.normalized() * 1e-4
        out.append((f, 'clear' if not hits else 'behind ' + ', '.join(dict.fromkeys(hits))))
    for f, v in out: print(f'VISIBLE {obj} f{f}: {v}')
    return out

def overlaps(a, b, frames, scene, gap=0.0):
    """For each frame: do the evaluated meshes of a and b intersect (or come within gap)?"""
    sc = bpy.data.scenes[scene]; bpy.context.window.scene = sc; out = []
    for f in frames:
        sc.frame_set(f); dg = bpy.context.evaluated_depsgraph_get()
        ta, tb = _world_tree(sc.objects[a], dg), _world_tree(sc.objects[b], dg)
        n = len(ta.overlap(tb)); out.append((f, n))
        print(f'OVERLAP {a} x {b} f{f}: {n} touching face pairs')
    return out

NS = {'bpy': bpy, 'Vector': Vector, 'stills': stills, 'revert': revert, 'save': save, 'run_script': run_script,
      'visible': visible, 'overlaps': overlaps, '_where': _where, '__name__': '__live__'}
open(os.path.join(JOBS, 'READY'), 'w').write(str(os.getpid()))
print('BSERVE ready, jobs in', JOBS, flush=True)
while not os.path.exists(os.path.join(JOBS, 'STOP')):
    for job in sorted(glob.glob(os.path.join(JOBS, '*.py'))):
        if os.path.exists(job + '.done'): continue
        buf = io.StringIO(); t = time.time(); ok = True
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            try: exec(compile(open(job).read(), job, 'exec'), NS)
            except BaseException: traceback.print_exc(); ok = False
        open(job + '.log', 'w').write(buf.getvalue() + f'\n[{"OK" if ok else "FAILED"} in {time.time() - t:.1f}s]\n')
        open(job + '.done', 'w').write('ok' if ok else 'failed')
    time.sleep(0.3)
print('BSERVE stopped')
