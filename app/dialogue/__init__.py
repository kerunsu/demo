"""儿童对话与浏览器 TTS 话术模块。"""

from .phrases import (
    format_onomatopoeia_question,
    get_phrase_bank,
    ordering_phrase_key,
    pick_phrase,
)
from .service import get_dialogue_service, init_dialogue_service
from .boundary import DialogueGateway, LegacyDialogueAdapter

__all__ = [
    "format_onomatopoeia_question",
    "get_phrase_bank",
    "pick_phrase",
    "ordering_phrase_key",
    "get_dialogue_service",
    "init_dialogue_service",
    "DialogueGateway",
    "LegacyDialogueAdapter",
]
