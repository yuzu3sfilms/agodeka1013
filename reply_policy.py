class ReplyPolicy:
    """
    v14.5:
    Decide which route to try based on current conversation state.

    Routes:
    - silence
    - canon
    - scene_replay
    - canon_then_scene
    - scene_then_fallback
    """

    def __init__(self):
        pass

    def plan(self, state: dict, has_relevant_episode: bool):
        intent = state.get("intent")
        preferred = state.get("preferred_route")
        should = state.get("should_consider_reply", False)

        if intent == "stop" or preferred == "silence":
            return {
                "reply": False,
                "routes": [],
                "reason": "stop_or_silence",
            }

        if not should and not has_relevant_episode:
            return {
                "reply": False,
                "routes": [],
                "reason": "no_call_no_relevance",
            }

        if preferred == "canon":
            routes = ["canon", "scene_replay", "fallback"]
        elif preferred == "canon_then_scene":
            routes = ["canon", "scene_replay", "fallback"]
        elif preferred == "scene_replay":
            routes = ["scene_replay", "canon", "fallback"]
        elif preferred == "scene_then_fallback":
            routes = ["scene_replay", "fallback"]
        elif preferred == "fallback_only":
            routes = ["fallback"]
        elif preferred == "episode_expand":
            routes = ["scene_replay", "fallback"]
        else:
            routes = ["scene_replay", "fallback"]

        return {
            "reply": True,
            "routes": routes,
            "reason": f"intent:{intent}|preferred:{preferred}",
        }
