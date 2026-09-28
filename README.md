# render-desk

The editor drops a `.blend` (or a `.zip` of the project folder) into Drive and an mp4
comes back. No terminal, no RunPod, no render settings.

    Nick-AE/render/1-drop-here     he puts files here
                  /2-working       STATUS.txt, updated as it renders
                  /3-finished      the mp4, a preview frame, and what it cost
                  /4-needs-a-fix   files that cannot render, and why, in plain English

Put `_draft` in a filename for a half-size, 32-sample look test that costs cents.

## Commands

    ./verify.sh                 prove the whole thing still works (24 checks)
    bin/renderdesk doctor       check the setup without rendering
    bin/renderdesk once         handle whatever is waiting, then exit
    bin/renderdesk watch        run forever (what launchd runs)
    bin/renderdesk cost         what rendering has cost, and the monthly projection
    bin/renderdesk render FILE  render one file directly

## Setup

    mkdir -p ~/.config/render-desk
    cp install/render.env.example ~/.config/render-desk/render.env
    # fill in RUNPOD_API_KEY and RUNPOD_VOLUME_ID, set PROVIDER=runpod

    cp install/com.nick.renderdesk.plist ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/com.nick.renderdesk.plist

`PROVIDER=local` renders on this Mac for free and is how the desk was proven.
`PROVIDER=runpod` rents a GPU per job and destroys it afterwards.

## On the box

    ssh root@46.62.230.121
    systemctl status render-desk          # is it running
    journalctl -u render-desk -f          # watch a job happen
    rd-visits 30                          # who hit the page in the last 30 minutes
    cd /opt/render-desk && python3 bin/renderdesk doctor

Deploy from this Mac with `deploy/ship.sh`. It never touches `/etc/render-desk/render.env`,
which holds the secrets; that is written once by `deploy/configure.sh`.

## What renting a GPU is actually like

Measured, not guessed:

- **Capacity fluctuates hard.** One job found all ten GPU types unavailable in EU-RO-1
  and fell back to another data centre; nine minutes later an L4 was free there. A job
  that finds nothing waits and retries rather than failing.
- **Setup is 1 to 5 minutes per job**, mostly downloading Blender. The network volume
  caches it, so only the first job in a given data centre pays the full price.
- **That overhead is charged once per clip, not per frame.** A 3-frame test that takes
  5 minutes to set up is not "100 seconds per frame".

## Samples: 128, decided by looking

Measured on Injection_Clip_v06 on 2026-09-28, frames 200, 445 and 700 rendered at
both 128 and 256 samples on the same 4090:

- PSNR between the two: 47 to 50 dB, above the range where a difference is visible
- Nick compared them at full pixel size and could not tell them apart
- 256 costs 2.4x, not 2x

So 128 stays. This scene is clean geometry and smooth shading, not glass or
volumetrics, which is why it converges so early. Re-run the comparison if a future
clip has caustics, heavy volumetrics or thin transparent surfaces, because those
are the cases where the answer changes.

## Cost

`bin/renderdesk cost` reads the ledger of real renders and projects the monthly bill:

    bin/renderdesk cost --clips 25 --seconds 35

Spend caps in `render.env` are hard stops. A job that would cross one is refused with a
note to the editor and nothing is charged.
