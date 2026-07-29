"""Compile Hashimoto's observed LINE behaviour into a compact persona policy.

The compiler is deliberately deterministic and offline.  It does not invent
traits with an LLM; every value is derived from corpus scenes and keeps its
sample count so the runtime can judge confidence.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from behavior_taxonomy import MEDIA, classify_reply, classify_stimulus


def _lines_before(scene: dict) -> list[tuple[str, str]]:
    out = []
    for line in scene.get("before", []) or []:
        if ":" not in line:
            continue
        speaker, text = line.split(":", 1)
        out.append((speaker.strip(), text.strip()))
    return out



def _ratio_map(counter: Counter) -> dict:
    total = sum(counter.values())
    if not total:
        return {}
    return {k: {"count": v, "probability": round(v / total, 4)} for k, v in counter.most_common()}


def _mean(values: list[int]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def compile_persona(scene_path: Path) -> dict:
    patterns = Counter()
    transitions = defaultdict(Counter)
    partner_patterns = defaultdict(Counter)
    partner_lengths = defaultdict(list)
    lengths: list[int] = []
    endings = Counter()
    reply_count = 0

    with gzip.open(scene_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            try:
                scene = json.loads(line)
            except Exception:
                continue
            reply = (scene.get("reply") or "").strip()
            if not reply or reply in MEDIA or len(reply) > 90:
                continue
            before = _lines_before(scene)
            pattern = classify_reply(reply)
            stimulus = classify_stimulus(before[-1][1] if before else "")
            patterns[pattern] += 1
            transitions[stimulus][pattern] += 1
            lengths.append(len(reply))
            reply_count += 1

            if reply.endswith(("？", "?")):
                endings["question_mark"] += 1
            if "笑" in reply or "草" in reply or re.fullmatch(r"[wｗ]+", reply, re.I):
                endings["laughter"] += 1
            if "。" in reply:
                endings["period"] += 1
            if "！" in reply or "!" in reply:
                endings["exclamation"] += 1

            # The nearest non-Hashimoto speaker is the strongest observable
            # approximation of addressee in a group chat.
            partner = None
            distance = None
            for idx, (speaker, _) in enumerate(reversed(before), start=1):
                if speaker not in {"橋本新", "Arata Hashimoto", "LIAR OF ARAKUN", "Unknown"}:
                    partner, distance = speaker, idx
                    break
            if partner:
                weight = max(1, 4 - min(distance or 4, 3))
                partner_patterns[partner][pattern] += weight
                partner_lengths[partner].extend([len(reply)] * weight)

    transitions_out = {
        stimulus: {"sample_count": sum(c.values()), "actions": _ratio_map(c)}
        for stimulus, c in sorted(transitions.items())
    }
    relationships = {
        partner: {
            "weighted_sample_count": sum(c.values()),
            "average_reply_length": _mean(partner_lengths[partner]),
            "action_policy": _ratio_map(c),
        }
        for partner, c in sorted(partner_patterns.items(), key=lambda kv: (-sum(kv[1].values()), kv[0]))
    }

    return {
        "schema_version": 2,
        "model": "hashimoto_layered_persona_policy",
        "source": scene_path.name,
        "evidence": {"usable_scenes": reply_count},
        "language": {
            "average_reply_length": _mean(lengths),
            "short_reply_probability": round(sum(1 for n in lengths if n <= 12) / reply_count, 4) if reply_count else 0,
            "long_reply_probability": round(sum(1 for n in lengths if n > 30) / reply_count, 4) if reply_count else 0,
            "surface_markers": {k: {"count": v, "probability": round(v / reply_count, 4)} for k, v in endings.items()},
        },
        "global_action_policy": _ratio_map(patterns),
        "situation_policy": transitions_out,
        "relationship_policy": relationships,
        "runtime": {
            "confidence_floor": 12,
            "max_policy_bonus": 14,
            "note": "Policy is a soft prior. Corpus evidence and current context remain mandatory.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenes", default="data/conversation_scenes.jsonl.gz")
    parser.add_argument("--output", default="data/persona_policy.json")
    args = parser.parse_args()
    payload = compile_persona(Path(args.scenes))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"compiled_persona_policy scenes={payload['evidence']['usable_scenes']} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
