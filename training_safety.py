import re


DANGER_PATTERNS = [
    ("pain_red_flag", r"鋭い痛み|激痛|しびれ|痺れ|腫れ|内出血|歩けない|動かない|息苦しい|胸痛|めまい|失神"),
    ("extreme_diet", r"断食|食べない|絶食|水だけ|一日.*(500|800|1000)\s*kcal|何も食べない|吐く|下剤"),
    ("dangerous_overtraining", r"毎日.*限界|毎日.*潰れる|倒れるまで|吐くまで|寝ないで|休まず"),
    ("substance", r"ステロイド|アナボリック|テストステロン|成長ホルモン|SARMs|サーム|クレンブテロール|利尿剤"),
    ("one_rep_max_risky", r"初心者.*MAX|毎回.*MAX|1RM.*毎回|マックス.*毎日"),
]


def check_training_safety(text: str):
    t = text or ""
    flags = []
    for name, pat in DANGER_PATTERNS:
        if re.search(pat, t, re.I):
            flags.append(name)

    if not flags:
        return {
            "safe": True,
            "flags": [],
            "message": None,
        }

    # Keep it clear and not preachy.
    if "pain_red_flag" in flags:
        msg = "それは無理して続けない方がいいです。鋭い痛み、しびれ、腫れ、動かしにくさがあるなら今日は中止で、必要なら整形外科とか専門家に見てもらった方が安全です。"
    elif "substance" in flags:
        msg = "薬物とかホルモン系で伸ばす方向は危ないので勧めません。まずは睡眠、食事、フォーム、漸進的な重量アップでいきましょう。"
    elif "extreme_diet" in flags:
        msg = "極端に食べない減量はやめた方がいいです。筋肉も落ちやすいし、体調も崩します。小さめのカロリー赤字とタンパク質、睡眠を優先しましょう。"
    elif "dangerous_overtraining" in flags:
        msg = "毎回潰れるまでやるのは続かないし怪我しやすいです。強い日と軽い日を分けた方が結果的に伸びます。"
    else:
        msg = "それは少し危なそうなので、無理に攻めず安全側で調整しましょう。"

    return {
        "safe": False,
        "flags": flags,
        "message": msg,
    }
