"""Session depth — scratchboard, turn state, message ledger, user model.

Single-loop ports of FAIL's ``server/sessions`` depth modules. The original
async + event-store backed designs are rewritten as small sync stores under
``<data_dir>/sessions_depth/`` so they can be called inline from the chat
flow without an event broker.
"""
from __future__ import annotations

from augment.sessions.message_ledger import MessageReceipt, MessageLedger
from augment.sessions.scratchboard import (
    ScratchboardFact,
    ScratchboardState,
    ScratchboardStore,
)
from augment.sessions.turn_state import TurnState, TurnStateStore
from augment.sessions.user_model import UserModelState, UserModelStore

__all__ = [
    "MessageLedger",
    "MessageReceipt",
    "ScratchboardFact",
    "ScratchboardState",
    "ScratchboardStore",
    "TurnState",
    "TurnStateStore",
    "UserModelState",
    "UserModelStore",
]
