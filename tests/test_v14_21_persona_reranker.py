from actual_reply_engine import ActualReplyEngine


def make_engine(scenes):
    e = ActualReplyEngine.__new__(ActualReplyEngine)
    e.min_score = 0
    e.scenes = scenes
    from collections import Counter
    e.reply_frequency = Counter()
    e.pattern_frequency = Counter()
    e.speaker_frequency = Counter()
    e._build_persona_statistics()
    return e


def scene(i, reply, speakers, anchors=("ペヤング",), before_question=False):
    return {
        "id": i,
        "reply": reply,
        "scene": f"Reiji Shioda: ペヤングどうする\n橋本新: {reply}",
        "anchors": list(anchors),
        "reply_tokens": [],
        "speakers": list(speakers),
        "has_question_before": before_question,
        "short": len(reply) <= 8,
    }


def test_same_partner_softly_reranks_eligible_scenes():
    scenes = [
        scene(1, "スクワット", ["村田"]),
        scene(2, "腕立てでいい", ["Reiji Shioda"]),
    ]
    e = make_engine(scenes)
    hits = e.search("ペヤング", current_speaker="Reiji Shioda", limit=10)
    assert hits[0]["reply"] == "腕立てでいい"
    assert any("same_partner:Reiji Shioda" in r for r in hits[0]["reasons"])


def test_pattern_frequency_is_behavior_prior_not_hard_filter():
    scenes = [
        scene(1, "やめときなよ", ["村田"]),
        scene(2, "それはやめとけ", ["坂口"]),
        scene(3, "無理", ["村田"]),
        scene(4, "ペヤング仙人", ["村田"]),
    ]
    e = make_engine(scenes)
    scored = e.score_scene(scenes[0], "ペヤング", "")
    assert scored is not None
    assert any("pattern_frequency:negative_advice" in r for r in scored["reasons"])
    # Rare eligible replies remain searchable; frequency does not delete them.
    hits = e.search("ペヤング", limit=10)
    assert any(h["reply"] == "ペヤング仙人" for h in hits)


def test_recent_context_overlap_adds_continuity():
    a = scene(1, "軽くやる", ["村田"], anchors=("ペヤング", "スクワット"))
    b = scene(2, "今日は休む", ["村田"], anchors=("ペヤング", "ベンチ"))
    e = make_engine([a, b])
    hits = e.search("ペヤング", context="user: スクワットの話\nassistant: 何回やる", limit=10)
    assert hits[0]["reply"] == "軽くやる"
    assert any("conversation_continuity:スクワット" in r for r in hits[0]["reasons"])


def test_no_current_anchor_still_blocks_replay():
    e = make_engine([scene(1, "よく言う返し", ["Reiji Shioda"]) for _ in range(20)])
    assert e.search("天気どう", current_speaker="Reiji Shioda") == []
