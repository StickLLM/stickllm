"""StickLLM 0.6.6: auto-rename after the main monologue, with llama backoff.

Same logic as Agent Zero's _chat_naming monologue_start hook, but deferred so
the utility-model call does not race the main generation on a saturated
llama-server. Retries briefly when the utility call still fails.
"""
from __future__ import annotations

import asyncio

from agent import AgentContext, AgentContextType, LoopData
from helpers.extension import Extension
from helpers.notification import NotificationManager, NotificationPriority, NotificationType
from plugins._chat_naming.helpers import naming

_UNSET_SCHEDULED_NAME = object()
# Short backoffs while the main reply's KV/slot is still draining.
_RETRY_DELAYS_SEC = (0.4, 1.0, 2.0, 4.0, 8.0)


class RenameChat(Extension):
    async def execute(self, loop_data: LoopData = LoopData(), **kwargs):
        if not self.agent or self.agent is not self.agent.context.agent0:
            return
        if self.agent.context.type != AgentContextType.USER:
            return
        if self.agent.context.get_output_data("parent_context_id"):
            return

        config = naming.get_config(self.agent)
        if not config["automatic_naming"]:
            return
        if self.agent.context.get_data(naming.MANUAL_NAME_KEY):
            return

        mode = config["automatic_naming_mode"]
        if mode == naming.MODE_ONCE and str(self.agent.context.name or "").strip():
            return

        messages = naming.get_user_messages(
            self.agent,
            limit=None if mode == naming.MODE_ONCE else naming.RECENT_USER_MESSAGES,
        )
        if not messages:
            return
        if mode == naming.MODE_ONCE:
            messages = messages[:1]

        asyncio.create_task(
            self.change_name(
                messages=messages,
                request_sequence=naming.latest_user_sequence(self.agent),
                only_if_unnamed=(mode == naming.MODE_ONCE),
                scheduled_name=self.agent.context.name,
            )
        )

    async def change_name(
        self,
        *,
        messages: list[str],
        request_sequence: int,
        only_if_unnamed: bool,
        scheduled_name: object = _UNSET_SCHEDULED_NAME,
    ) -> None:
        if not self.agent:
            return

        last_exc: BaseException | None = None
        for attempt, delay in enumerate(_RETRY_DELAYS_SEC):
            try:
                new_name = await naming.generate_name(
                    self.agent,
                    user_messages=messages,
                    current_name=self.agent.context.name,
                )
                if only_if_unnamed and str(self.agent.context.name or "").strip():
                    return
                if naming.latest_user_sequence(self.agent) != request_sequence:
                    return
                if (
                    scheduled_name is not _UNSET_SCHEDULED_NAME
                    and self.agent.context.name != scheduled_name
                ):
                    return
                if self.agent.context.get_data(naming.MANUAL_NAME_KEY):
                    return
                if AgentContext.get(self.agent.context.id) is not self.agent.context:
                    return
                naming.save_context_name(self.agent, new_name)
                return
            except Exception as exc:  # noqa: BLE001 — match upstream toast path
                last_exc = exc
                if attempt + 1 >= len(_RETRY_DELAYS_SEC):
                    break
                await asyncio.sleep(delay)

        NotificationManager.send_notification(
            type=NotificationType.ERROR,
            priority=NotificationPriority.NORMAL,
            title="Chat Naming Failed",
            message=(
                "Automatic chat naming failed after the reply "
                "(utility model busy or unreachable)."
            ),
            detail=(
                "StickLLM runs chat naming after the main reply and retries while "
                "llama-server is busy. If this keeps failing, check Settings > Models > "
                "Utility Model and that the chat model answers."
                + (f" Last error: {last_exc}" if last_exc else "")
            ),
            display_time=10,
            group="chat_naming",
            id=f"chat_naming_failed_{self.agent.context.id}",
        )
