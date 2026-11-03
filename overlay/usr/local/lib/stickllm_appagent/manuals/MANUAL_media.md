# Media (StickLLM pictures, audio, and video) - knowledge pack

STATE lists the folder root, the path inside it, the names in this folder, and the file on stage.
A name with dir true is a folder. kind is img, audio, or video. paused is true when sound or video is stopped.

## Fixed meanings for vague words
| user says | actions |
|---|---|
| play NAME, open NAME, show NAME | `open "NAME"` using a name printed in STATE |
| go into the folder NAME | `open "NAME"` when that entry is a folder |
| up, back, parent folder | `up` |
| switch to the vault, use root ID | `root "ID"` |
| play, resume | `play` (the file already on stage) |
| pause, stop | `pause` |

## Rules for the executor
- Send exactly ONE action per reply, copied from the plan.
- `open` only a name that is in this folder. If it is not listed, `up` or say it is not here. Do not invent a file name.
- `play` and `pause` need a video or audio file already on stage. A picture has no play button.

## Example plan
Request "play the clip named cats.mp4" when cats.mp4 is in the folder list:
{"understanding": "open cats.mp4 from this folder", "plan": ["open \"cats.mp4\""]}
