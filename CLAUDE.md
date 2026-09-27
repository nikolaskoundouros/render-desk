# render-desk
drop a .blend in Drive, get a finished mp4 back: on-demand GPU rendering for Nick's editor, no terminal

Done means `./verify.sh` exits 0. Agents never edit verify.sh, checks/ or program.md (the gate blocks it).
Needs Nick: the RunPod API key and network volume, sharing the Drive folder with the editor,
raising a spend cap, and any first paid render on a new GPU type.

The editor never sees a terminal, RunPod, or a render setting. He sees four folders in Drive
and a STATUS.txt written in plain English. Everything technical stays on this side.

Rules this code exists to keep:
- a rented GPU is always destroyed, including when the render crashes or the desk is killed
- frames live on the network volume, so an interrupted job resumes instead of paying twice
- a file that cannot render well (missing textures, no camera, newer Blender) is refused
  before a GPU is rented, not after
- every job records seconds per frame and dollars, because measuring the real cost is the
  reason this was built
