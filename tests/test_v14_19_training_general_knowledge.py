from types import SimpleNamespace

from ai_training_advisor import AITrainingAdvisor


class FakeCompletions:
    def __init__(self, text):
        self.text = text

    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))]
        )


class FakeClient:
    def __init__(self, text):
        self.chat = SimpleNamespace(completions=FakeCompletions(text))


def test_general_training_uses_standard_general_knowledge_when_no_client():
    advisor = AITrainingAdvisor(client=None)
    result = advisor.answer("c1", "筋トレ教えて")
    assert result["used"] is True
    assert "スクワット" in result["answer"]
    assert "押す種目" in result["answer"]
    assert "引く種目" in result["answer"]
    assert "シャッタースローペチョ" not in result["answer"]


def test_invented_exercise_name_is_rejected_and_replaced():
    fake = FakeClient(
        "初心者ならスクワット、ベンチプレス、シャッタースローペチョを3セットです。"
    )
    advisor = AITrainingAdvisor(client=fake)
    result = advisor.answer("c1", "筋トレ教えて")
    assert result["used"] is True
    assert result["kind"].endswith("validated_fallback")
    assert "シャッタースローペチョ" not in result["answer"]
    assert "スクワット" in result["answer"]


def test_standard_exercise_names_are_accepted():
    fake = FakeClient(
        "週2〜3回でいいです。スクワット、ベンチプレス、ラットプルダウンを各3セット。"
    )
    advisor = AITrainingAdvisor(client=fake)
    result = advisor.answer("c1", "筋トレ教えて")
    assert result["used"] is True
    assert result["kind"] == "ai_training_general_training"
    assert "ラットプルダウン" in result["answer"]


def test_unknown_user_term_can_be_explained_without_validator_loop():
    advisor = AITrainingAdvisor(client=None)
    valid, info = advisor._validate_general_knowledge_answer(
        "シャッタースローペチョという名前は一般的な種目ではありません。",
        "シャッタースローペチョって何？",
    )
    assert valid is True
    assert info["unknown_katakana"] == []
