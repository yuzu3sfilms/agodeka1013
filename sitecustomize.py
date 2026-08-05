"""Project AGO v14.25.2 — length-neutral historical Replay policy.

Loaded automatically by normal Python startup from the repository root.

Historical Replay policy:
- No bonus or penalty based only on reply length.
- Remove the former 90-character rejection.
- Preserve scene, anchor, speaker, relationship and intent scoring.
- Leave generated Groq/persona reply length policy unchanged.
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import sys
from typing import Any


_TARGET = "actual_reply_engine"
_PATCH_MARKER = "_ago_v14_25_2_length_neutral"


def _patch_actual_reply_engine(module: Any) -> None:
    engine = getattr(module, "ActualReplyEngine", None)
    if engine is None or getattr(engine, _PATCH_MARKER, False):
        return

    original_score_scene = engine.score_scene

    def length_neutral_bad_replay(self, reply: str):
        text = (reply or "").strip()
        if not text:
            return True

        bad_direct = getattr(module, "BAD_DIRECT_REPLIES", set())
        if text in bad_direct:
            return True

        # Delivery guard only, not a quality judgement.
        max_chars = int(os.environ.get("REPLAY_TRANSPORT_MAX_CHARS", "4500"))
        return len(text) > max_chars

    def length_neutral_score_scene(
        self,
        scene: dict,
        user_text: str,
        context: str,
        topic_terms=None,
        context_topic_terms=None,
        intent: str = "",
        current_speaker: str | None = None,
    ):
        hit = original_score_scene(
            self,
            scene,
            user_text,
            context,
            topic_terms=topic_terms,
            context_topic_terms=context_topic_terms,
            intent=intent,
            current_speaker=current_speaker,
        )
        if not hit:
            return None

        reply = hit.get("reply") or ""
        length = len(reply)
        reasons = list(hit.get("reasons") or [])

        # Cancel the original length-only adjustment.
        if length <= 4:
            hit["score"] -= 5
            reasons = [x for x in reasons if x != "very_short_actual"]
        elif length <= 18:
            hit["score"] -= 14
            reasons = [x for x in reasons if x != "short_actual"]
        elif length <= 35:
            hit["score"] -= 6
            reasons = [x for x in reasons if x != "medium_actual"]
        else:
            hit["score"] += 8
            reasons = [x for x in reasons if x != "longish_actual"]

        reasons.append(f"replay_length_neutral:{length}")
        hit["reasons"] = reasons
        return hit

    engine._is_bad_replay = length_neutral_bad_replay
    engine.score_scene = length_neutral_score_scene
    setattr(engine, _PATCH_MARKER, True)


class _PatchLoader(importlib.abc.Loader):
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def create_module(self, spec):
        create = getattr(self.wrapped, "create_module", None)
        return create(spec) if create else None

    def exec_module(self, module):
        self.wrapped.exec_module(module)
        _patch_actual_reply_engine(module)


class _PatchFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != _TARGET:
            return None

        index = sys.meta_path.index(self)
        sys.meta_path.pop(index)
        try:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        finally:
            sys.meta_path.insert(index, self)

        if spec is not None and spec.loader is not None:
            spec.loader = _PatchLoader(spec.loader)
        return spec


if _TARGET in sys.modules:
    _patch_actual_reply_engine(sys.modules[_TARGET])
elif not any(isinstance(x, _PatchFinder) for x in sys.meta_path):
    sys.meta_path.insert(0, _PatchFinder())
