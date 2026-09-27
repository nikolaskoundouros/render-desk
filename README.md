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

## Cost

`bin/renderdesk cost` reads the ledger of real renders and projects the monthly bill:

    bin/renderdesk cost --clips 25 --seconds 35

Spend caps in `render.env` are hard stops. A job that would cross one is refused with a
note to the editor and nothing is charged.
