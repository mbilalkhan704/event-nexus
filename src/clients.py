"""Model clients. Each implements ModelClient.generate(system_prompt, user_message) -> text."""
import json
import os
import time
import urllib.error
import urllib.request

import qa_core

try:
    from dotenv import load_dotenv
    load_dotenv()                      # variables already set in the shell win
except ImportError:
    pass


def _load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class ReplayClient(qa_core.ModelClient):
    """Replays replies generated elsewhere (Kaggle), so the same pipeline and scorer judge them.
    A reply is found by its exact user message, built by the same function the pipeline uses."""

    def __init__(self, replies_path, split):
        stem = os.path.basename(replies_path)
        stem = stem[:-len(".jsonl")] if stem.endswith(".jsonl") else stem
        if stem.startswith(f"{split}_"):
            stem = stem[len(split) + 1:]
        self.name = f"replay_{stem}"
        by_id = {r["id"]: r for r in _load(replies_path)}
        self.replies, missing, conflicts = {}, [], 0
        for it in _load(f"eval/{split}.jsonl"):
            rec = by_id.get(it["id"])
            if rec is None:
                missing.append(it["id"])
                continue
            msg = qa_core.build_user_message(it["question"], it["events"])
            if msg in self.replies and self.replies[msg] != rec["reply"]:
                conflicts += 1          # same input, different reply: the first one is kept
                continue
            self.replies[msg] = rec["reply"]
        print(f"replay: {len(self.replies)} replies loaded from {replies_path}")
        if missing:
            print(f"replay WARNING: no reply for {len(missing)} {split} items, e.g. {missing[:5]}")
        if conflicts:
            print(f"replay WARNING: {conflicts} items share an input with a different reply")

    def generate(self, system_prompt, user_message):
        if user_message not in self.replies:
            raise KeyError("no stored reply for this question and context")
        return self.replies[user_message]


class OpenAIClient(qa_core.ModelClient):
    """Any OpenAI-compatible chat server: llama-server (local or behind a tunnel), Ollama, ...
    Environment: LLM_URL (required), LLM_API_KEY, LLM_MODEL, LLM_TAG (names the run), LLM_TIMEOUT."""

    def __init__(self, fewshot=None):
        self.url = os.environ.get("LLM_URL", "").rstrip("/")
        if not self.url:
            raise SystemExit("set LLM_URL, for example http://127.0.0.1:8080")
        self.key = os.environ.get("LLM_API_KEY", "")
        self.model = os.environ.get("LLM_MODEL", "local")
        self.name = "llm_" + os.environ.get("LLM_TAG", self.model)
        self.timeout = int(os.environ.get("LLM_TIMEOUT", "900"))
        self.fewshot = fewshot or []

    def generate(self, system_prompt, user_message):
        messages = [{"role": "system", "content": system_prompt}]
        for u, a in self.fewshot:
            messages += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
        messages.append({"role": "user", "content": user_message})
        body = json.dumps({"model": self.model, "messages": messages, "temperature": 0,
                           "max_tokens": 512, "cache_prompt": True, "stream": True,
                           "chat_template_kwargs": {"enable_thinking": False}}).encode()
        headers = {"Content-Type": "application/json"}
        if self.key:
            headers["Authorization"] = "Bearer " + self.key
        last = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(self.url + "/v1/chat/completions", data=body, headers=headers)
                parts = []
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    for raw in r:
                        line = raw.decode("utf-8", "ignore").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        choices = json.loads(data).get("choices") or []
                        if choices:
                            parts.append(choices[0].get("delta", {}).get("content") or "")
                return "".join(parts).strip()
            except urllib.error.HTTPError as e:
                if e.code < 500:
                    raise SystemExit(f"server answered {e.code}: check LLM_URL and LLM_API_KEY")
                last = e
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                last = e
            time.sleep(5 * (attempt + 1))
        raise SystemExit(f"server not reachable after 3 attempts: {last}")


def get_client(name, fewshot=None, replies=None, split="dev"):
    if name == "fake":
        return qa_core.FakeClient("REFUSE: placeholder")
    if name == "replay":
        if not replies:
            raise SystemExit("--client replay needs --replies <file.jsonl>")
        return ReplayClient(replies, split)
    if name in ("llm", "openai"):
        return OpenAIClient(fewshot)
    raise SystemExit(f"unknown client '{name}'")