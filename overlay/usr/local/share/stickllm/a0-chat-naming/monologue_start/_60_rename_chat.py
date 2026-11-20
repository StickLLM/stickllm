"""StickLLM 0.6.6: no-op at monologue_start.

Upstream Agent Zero schedules chat naming here, concurrent with the main
utility/chat call on the same llama-server. On a busy stick that fails and
surfaces as "Utility Model was not reachable." Naming runs at monologue_end
instead (see ../monologue_end/_60_rename_chat.py), after the main reply.
"""
from __future__ import annotations

from agent import LoopData
from helpers.extension import Extension


class RenameChat(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        return
