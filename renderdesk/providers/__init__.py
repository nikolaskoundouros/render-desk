"""Render providers. The desk does not care which machine does the work.

Every provider implements:
    render(blend: Path, frames_dir: Path, opts: dict, log: callable) -> dict
and returns a dict describing what actually rendered (device, gpu, seconds, cost).
"""


def get(name, cfg):
    if name == "local":
        from .local import LocalProvider

        return LocalProvider(cfg)
    if name == "runpod":
        from .runpod import RunPodProvider

        return RunPodProvider(cfg)
    raise ValueError(f"unknown provider {name!r} (expected 'local' or 'runpod')")
