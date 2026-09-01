import pytest

from src.llm.client import GMIError, GMIClient


class FakeResp:
    def __init__(self, status_code=200, body=None, text="", headers=None):
        self.status_code = status_code
        self._body = body
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no json body")
        return self._body


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def post(self, *a, **k):
        self.calls += 1
        return self.responses.pop(0)


def _client(monkeypatch, responses) -> tuple[GMIClient, FakeHttp]:
    monkeypatch.setattr("src.llm.client.time.sleep", lambda s: None)
    c = GMIClient()
    http = FakeHttp(responses)
    c._http = http
    return c, http


def _ok(content="hello"):
    return FakeResp(200, {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


def test_client_error_fails_fast_without_retries(monkeypatch):
    """400/401/403 never succeed on retry — burn one request, not five."""
    c, http = _client(monkeypatch, [FakeResp(401, text="unauthorized")])
    with pytest.raises(GMIError, match="401"):
        c.chat([{"role": "user", "content": "q"}])
    assert http.calls == 1


def test_429_then_success_retries(monkeypatch):
    c, http = _client(monkeypatch, [
        FakeResp(429, text="rate limited", headers={"Retry-After": "1"}),
        _ok("recovered"),
    ])
    assert c.chat([{"role": "user", "content": "q"}]) == "recovered"
    assert http.calls == 2


def test_5xx_retries_then_raises_with_status(monkeypatch):
    c, http = _client(monkeypatch, [FakeResp(503, text="down")] * 5)
    with pytest.raises(GMIError, match="503"):
        c.chat([{"role": "user", "content": "q"}], retries=4)
    assert http.calls == 5


def test_malformed_body_raises_gmi_error(monkeypatch):
    c, http = _client(monkeypatch, [FakeResp(200, {"error": "unexpected shape"})])
    with pytest.raises(GMIError, match="malformed"):
        c.chat([{"role": "user", "content": "q"}])
    assert http.calls == 1


def test_null_content_raises_with_finish_reason(monkeypatch):
    body = {"choices": [{"message": {"content": None}, "finish_reason": "length"}]}
    c, _ = _client(monkeypatch, [FakeResp(200, body)])
    with pytest.raises(GMIError, match="finish_reason=length"):
        c.chat([{"role": "user", "content": "q"}])


def test_402_not_on_plan_raises_immediately(monkeypatch):
    c, http = _client(monkeypatch, [FakeResp(402, text="plan limit")])
    with pytest.raises(GMIError, match="402"):
        c.chat([{"role": "user", "content": "q"}], retries=4)
    assert http.calls == 1
