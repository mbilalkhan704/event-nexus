"""Model clients. Each implements ModelClient.generate(system_prompt, user_message) -> text."""

import qa_core


def get_client(name, fewshot=None):
    if name == "fake":
        return qa_core.FakeClient("REFUSE: placeholder")
    raise SystemExit(f"unknown client '{name}'")