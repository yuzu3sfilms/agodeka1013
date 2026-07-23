from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SpeakerProfile:
    canonical_name: str = ""
    display_name: str = ""
    address: str = ""
    aliases: tuple[str, ...] = ()
    confidence: float = 0.0
    source: str = "unknown"

    @property
    def known(self) -> bool:
        return bool(self.canonical_name and self.address)

    def prompt_block(self) -> str:
        if not self.known:
            return (
                "現在の発言者は特定できない。相手を『あなた』『君』と呼ばず、"
                "名前も推測せず、主語を省略する。"
            )
        return (
            f"現在の発言者: {self.canonical_name}\n"
            f"LINE表示名: {self.display_name or '不明'}\n"
            "この情報は発言者識別専用。呼称生成の根拠には使わない。"
            "相手の名前・姓・名・二人称を返信へ付けず、主語を省略する。"
        )


class SpeakerResolver:
    """Resolve a live LINE sender to a person and learned form of address."""

    def __init__(self, path: str = "data/speaker_profiles.json"):
        self.path = path
        self.profiles = []
        self.user_map = {}
        self._load()

    @staticmethod
    def _norm(value: str) -> str:
        s = (value or "").strip().lower()
        s = re.sub(r"[\s　_\-・･]+", "", s)
        return s

    def _load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.profiles = data.get("profiles", []) or []
            self.user_map = data.get("line_user_map", {}) or {}
        except Exception as e:
            print("speaker_profiles_load_error:", repr(e), flush=True)
            self.profiles = []
            self.user_map = {}

    def resolve(self, sender_id: str | None = None, display_name: str | None = None) -> SpeakerProfile:
        sender_id = sender_id or ""
        display_name = (display_name or "").strip()

        # Manual/stable LINE userId mapping always wins.
        canonical = self.user_map.get(sender_id)
        if canonical:
            p = self._by_canonical(canonical)
            if p:
                return self._to_profile(p, display_name, 1.0, "line_user_map")

        nd = self._norm(display_name)
        if nd:
            exact = []
            partial = []
            for p in self.profiles:
                names = [p.get("canonical_name", ""), *(p.get("aliases", []) or [])]
                norms = [self._norm(x) for x in names if x]
                if nd in norms:
                    exact.append(p)
                elif len(nd) >= 3 and any(nd in x or x in nd for x in norms if len(x) >= 3):
                    partial.append(p)
            if len(exact) == 1:
                return self._to_profile(exact[0], display_name, 0.96, "display_name_exact")
            if not exact and len(partial) == 1:
                return self._to_profile(partial[0], display_name, 0.72, "display_name_partial")

        return SpeakerProfile(display_name=display_name, source="unresolved")

    def _by_canonical(self, canonical: str):
        nc = self._norm(canonical)
        for p in self.profiles:
            if self._norm(p.get("canonical_name", "")) == nc:
                return p
        return None

    @staticmethod
    def _to_profile(p: dict, display_name: str, confidence: float, source: str) -> SpeakerProfile:
        addresses = p.get("addresses_from_arata", []) or []
        address = p.get("preferred_address") or (addresses[0] if addresses else "")
        return SpeakerProfile(
            canonical_name=p.get("canonical_name", ""),
            display_name=display_name,
            address=address,
            aliases=tuple(p.get("aliases", []) or []),
            confidence=confidence,
            source=source,
        )
