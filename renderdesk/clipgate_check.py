"""The clip gate inside the GPU tool (Nick, 2026-10-16: "the process has to be bulletproof though. also build a something
that enforces the checks"). workbench run and live do call refusal() before anything reaches a pod.

A render of moving pictures is any command that runs render_range.py, Blender with -a, bpy's render(animation=True), or a
script whose name says final or preview. It must name every .blend it renders by absolute path under
/Users/nick/Desktop/<clip>/, and `clip-gate allows` must clear exactly those files:
- a rough motion test (PCT at most 30 and SPP at most 8, set in the command) needs the basics pass;
- anything else needs Nick's approval of the still render (a final needs his "approve final").
Stills (single frames for checks) are not touched. The cleared blends are pushed to the pod again right before the render,
so the pod renders exactly the files that were reviewed. On the Mac there is no gate: renders run from clip-a only."""
import os, re, shlex, subprocess

GATE = '/usr/local/bin/clip-gate'
RENDER = re.compile(r'render_range\.py|blender\S*\s[^|;&]*\s-a(?:\s|$)|\$BLENDER\s[^|;&]*\s-a(?:\s|$)|render\(\s*animation\s*=\s*True'
                    r'|\b\w*(?:final|preview)\w*\.(?:sh|py)\b', re.I)
BLEND = re.compile(r'(/Users/nick/Desktop/([A-Za-z0-9_-]+)/[^\s"\';|&]+\.blend)(?![\w.])')
RELBLEND = re.compile(r'(?<![/\w])[\w./-]*\.blend(?![\w.])')


def _env_num(cmd, key):
    m = re.findall(rf'\b{key}=(\d+)', cmd)
    return int(m[-1]) if m else None


def blends_in(command):
    return [(m.group(1), m.group(2)) for m in BLEND.finditer(command)]


STILLS = re.compile(r'still\.py\s+--\s+\S+((?:\s+\d+)+)')
MAX_STILLS = 16


def is_render(command):
    if RENDER.search(command):
        return True
    return any(len(m.group(1).split()) > MAX_STILLS for m in STILLS.finditer(command))   # many "stills" are an animation


def refusal(command):
    """None if the command may run, else why not."""
    if not is_render(command):
        return None
    if not os.path.exists(GATE):
        return 'renders of moving pictures run from clip-a, where the clip gate checks them'
    found = blends_in(command)
    abs_paths = {b for b, _ in found}
    loose = [r for r in RELBLEND.findall(command) if not any(r == b or b.endswith(r) for b in abs_paths) and '/' not in r[:1]]
    if not found or loose:
        return ('name every .blend the render uses by its absolute path under /Users/nick/Desktop/<clip>/ '
                '(relative or missing paths cannot be checked)')
    clips = {c for _, c in found}
    if len(clips) > 1:
        return 'one clip per render command'
    clip = clips.pop()
    pct, spp = _env_num(command, 'PCT'), _env_num(command, 'SPP')
    mode = 'motion' if (pct is not None and spp is not None and pct <= 30 and spp <= 8) else 'preview'
    if re.search(r'final', command, re.I) and mode != 'motion':
        mode = 'final'
    r = subprocess.run([GATE, 'allows', clip, mode] + sorted(abs_paths), capture_output=True, text=True)
    if r.returncode != 0:
        return (r.stdout.strip() or r.stderr.strip() or 'clip gate refused') + f'  [{clip}, {mode}]'
    return None


def cleared_blends(command):
    """the absolute .blend paths in a cleared render command (pushed to the pod before it runs)"""
    return sorted({b for b, _ in blends_in(command)}) if is_render(command) else []
