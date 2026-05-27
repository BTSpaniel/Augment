"""Mind layer — personality, drives, background thinking, agent self-state.

Ported from FAIL's ``server/mind`` package. Pass 3 adds inner monologue,
beliefs / world-model, self-model, metacognition, and a learned user profile
that lives alongside :class:`augment.sessions.user_model.UserModelStore`.
"""
from __future__ import annotations

from augment.mind.beliefs import Beliefs
from augment.mind.drives import Drive, DriveSystem
from augment.mind.metacognition import Metacognition
from augment.mind.mind import Mind, get_mind, init_mind
from augment.mind.monologue import InnerMonologue
from augment.mind.personality import BigFive, Mood, Personality
from augment.mind.self_model import SelfModel
from augment.mind.thinking import BackgroundThinking
from augment.mind.user_model import UserModel

__all__ = [
    "BackgroundThinking",
    "Beliefs",
    "BigFive",
    "Drive",
    "DriveSystem",
    "InnerMonologue",
    "Metacognition",
    "Mind",
    "Mood",
    "Personality",
    "SelfModel",
    "UserModel",
    "get_mind",
    "init_mind",
]
