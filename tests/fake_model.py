"""
tests/fake_model.py

A stand-in for the Anthropic client: returns scripted responses, records
every request, and never touches the network. Each scripted step is one of:
  {item id: (summary, why)}   a normal JSON response
  "refusal"                   stop_reason "refusal", no text
  "garbage"                   text that is not JSON
  an Exception instance       raised by messages.create
"""

import json
from types import SimpleNamespace


class FakeAPIError(Exception):
    def __init__(self, status_code, message=""):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class FakeClient:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)

    def sent_ids(self, call: int) -> list:
        body = self.requests[call]["messages"][0]["content"]
        return [entry["id"] for entry in json.loads(body[body.index("["):])]

    def _create(self, **request):
        self.requests.append(request)
        step = self.steps.pop(0) if self.steps else {}
        usage = SimpleNamespace(input_tokens=3000, output_tokens=900,
                                cache_read_input_tokens=0, cache_creation_input_tokens=0)
        if isinstance(step, Exception):
            raise step
        if step == "refusal":
            return SimpleNamespace(stop_reason="refusal", content=[], usage=usage)
        text = "not json" if step == "garbage" else json.dumps(
            {"items": [{"id": k, "summary": v[0], "why_it_matters": v[1]} for k, v in step.items()]})
        return SimpleNamespace(stop_reason="end_turn", usage=usage,
                               content=[SimpleNamespace(type="text", text=text)])
