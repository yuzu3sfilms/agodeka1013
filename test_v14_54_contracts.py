from ago_runtime import PersonaArchive, MeaningResolver, ContractBuilder, DialogueState

archive=PersonaArchive()
resolver=MeaningResolver(archive)
builder=ContractBuilder(archive)
state=DialogueState()
questions=[
    "自我芽生えた？",
    "俺のことどう思う？",
    "村田は？",
    "せっきーは？",
    "明日13時集合でいい？",
    "やっぱ14時にしようぜww",
    "てか俺最近ギター買いすぎなんだよね",
]
for i,q in enumerate(questions,1):
    m=resolver.resolve(q,state,"Reiji Shioda",False)
    c=builder.build(m,state,"Reiji Shioda")
    print(f"{i}. {q}")
    print(" intent:",m.intent,"act:",m.act,"replay:",c.can_replay,"confidence:",c.source_confidence)
    print(" source:",c.primary and c.primary.get("source"))
    print(" anchor:",c.primary and c.primary.get("reply"))
    print(" fallback:",c.fallback)
    print(" content:",c.content_sources[:3])
    print()
    state.turns.extend([
        {"role":"user","text":q,"speaker":"Reiji Shioda"},
        {"role":"assistant","text":"[offline-test]"},
    ])
    resolver.commit(state,m,"Reiji Shioda")
