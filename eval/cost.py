"""Claude 호출 토큰을 원장 파일에 쌓고 예산을 넘기면 멈춘다(run.py·masked.py 공용).

L7 코드는 건드리지 않고 llm_client._decode_event를 감싸 SSE usage 이벤트만 엿봄.
단가는 Anthropic 공식가(USD/MTok). 게이트웨이 실단가와 다를 수 있음.
"""

import json
from pathlib import Path
from typing import Any

from upstream import llm_client

PRICE = {
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-haiku-5-5": (0.1, 0.5),
}
_tally = {"in": 0, "out": 0}
_orig = llm_client._decode_event


def _spy(data: str) -> dict[str, Any]:
    ev = _orig(data)
    u = ev.get("message", {}).get("usage") if ev.get("type") == "message_start" else ev.get("usage")
    if isinstance(u, dict):
        _tally["in"] += u.get("input_tokens", 0) or 0
        _tally["out"] += u.get("output_tokens", 0) or 0
    return ev


class Budget:
    def __init__(self, ledger: str, model: str, limit: float) -> None:
        self.path, self.model, self.limit = Path(ledger).expanduser(), model, limit
        self.price = PRICE.get(model)
        if model.startswith("claude") and self.price is None:
            raise SystemExit(f"단가 모름: {model}")
        if self.price:
            llm_client._decode_event = _spy

    def spent(self) -> float:
        if not self.path.exists():
            return 0.0
        lines = self.path.read_text(encoding="utf-8").splitlines()
        rows = (json.loads(x) for x in lines if x.strip())
        return sum(r["usd"] for r in rows)

    def record(self, tag: str) -> float:
        """직전 레코드의 토큰을 원장에 남기고 누적 USD를 돌려준다."""
        if not self.price:
            return 0.0
        usd = (_tally["in"] * self.price[0] + _tally["out"] * self.price[1]) / 1e6
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"tag": tag, "model": self.model, **_tally, "usd": usd}) + "\n")
        _tally.update({"in": 0, "out": 0})
        return self.spent()

    def over(self) -> bool:
        return bool(self.price) and self.spent() >= self.limit


if __name__ == "__main__":
    ev = '{"type":"message_start","message":{"usage":{"input_tokens":1000000,"output_tokens":1}}}'
    b = Budget("/dev/null", "claude-sonnet-5-5", 1.0)
    _spy(ev)
    _spy('{"type":"message_delta","usage":{"output_tokens":100000}}')
    assert _tally == {"in": 1000000, "out": 100001}, _tally  # noqa: S101
    print("ok")
