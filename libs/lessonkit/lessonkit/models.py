"""Lesson-script models: the one contract every service and the Android app share."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Alignment(BaseModel):
    chars: list[str] = Field(default_factory=list)
    start: list[float] = Field(default_factory=list)  # seconds
    end: list[float] = Field(default_factory=list)


class Action(BaseModel):
    type: Literal["write", "line", "arrow", "circle", "box", "underline", "brace", "highlight", "clear"]
    text: Optional[str] = None
    x: float = 0.0
    y: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    r: float = 0.0
    size: Literal["s", "m", "l"] = "m"
    color: Literal["white", "yellow", "green", "red", "blue"] = "white"


class LessonStep(BaseModel):
    id: str
    say: str
    actions: list[Action] = Field(default_factory=list)
    pause_ms: int = 300
    audio_url: Optional[str] = None
    alignment: Optional[Alignment] = None


class LessonScript(BaseModel):
    version: int = 1
    question_id: str
    title: str
    language: Literal["hinglish", "hindi", "english"] = "hinglish"
    trick_id: str = ""
    estimated_seconds: int = 0
    works_when: str = ""
    answer: str = ""
    steps: list[LessonStep]


class Question(BaseModel):
    id: str
    exam: str = ""
    subject: str = ""
    text: str
    options: list[str] = Field(default_factory=list)
    correct_option: str = ""


class LessonBundle(BaseModel):
    """One question plus all of its verified trick lessons."""
    question: Question
    lessons: list[LessonScript]
