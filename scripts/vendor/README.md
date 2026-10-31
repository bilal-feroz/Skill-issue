# Vendored third-party code

| File | Source | License |
|---|---|---|
| `bx_sculpt.py` | `scenario-blender-sculpting/scripts/bx_sculpt.py` from [scenario-labs/skills](https://github.com/scenario-labs/skills) (commit 7f4b801), the Blender Expert Skills family | MIT, see `LICENSE-scenario-labs-skills.txt` |

`bx_sculpt.Clay` (signed-distance "clay" meshed with OpenVDB) builds the student's head as
one integrated sculpt (cranium, lower face, cheeks, chin, nose and ears blended together) and
his hair as a shell that follows the skull, plus the quiff and combed clumps.
It's vendored unmodified so the project builds without the skill installed.
