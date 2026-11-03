"""Nemotron 페르소나 + 가상 PII + 템플릿으로 평가 레코드를 만든다.

uv run python eval/build_dataset.py --personas <parquet> --templates eval/templates.yaml [손작성.yaml ...] \
    --per-template 2 --out <out.jsonl>
"""

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml

SLOT_TYPES = {
    "NAME": "PERSON_KO",
    "PHONE": "PHONE_NUMBER",
    "EMAIL": "EMAIL_ADDRESS",
    "AGE": "AGE",
    "DOB": "DATE_OF_BIRTH",
    "RRN": "KR_RRN",
    "FRN": "KR_FRN",
    "PASSPORT": "KR_PASSPORT",
    "LICENSE": "KR_DRIVER_LICENSE",
    "BRN": "KR_BRN",
    "ORDER_ID": "ORDER_ID",
    "TRACKING": "TRACKING_NUMBER",
    "CUSTOMER_ID": "CUSTOMER_ID",
    "CUSTOMS_ID": "CUSTOMS_CLEARANCE_ID",
    "ACCOUNT": "ACCOUNT_NUMBER",
    "ADDRESS_ROAD": "ADDRESS_ROAD",
    "ADDRESS_LOT": "ADDRESS_LOT",
    "ADDRESS_DETAIL": "ADDRESS_DETAIL",
}  # 나머지 슬롯(DATE, AMOUNT, NET, BANK)은 PII 아님

PROVINCES = {
    "서울": "서울특별시",
    "부산": "부산광역시",
    "대구": "대구광역시",
    "인천": "인천광역시",
    "광주": "광주광역시",
    "대전": "대전광역시",
    "울산": "울산광역시",
    "세종": "세종특별자치시",
    "경기": "경기도",
    "강원": "강원특별자치도",
    "충청북": "충청북도",
    "충청남": "충청남도",
    "전북": "전북특별자치도",
    "전라남": "전라남도",
    "경상북": "경상북도",
    "경상남": "경상남도",
    "제주": "제주특별자치도",
}
ROADS = ["중앙로", "시민로", "문화로", "공원로", "역전로", "대학로", "평화로", "새마을로"]
BANKS = {
    "국민은행": (6, 2, 6),
    "신한은행": (3, 3, 6),
    "우리은행": (4, 3, 6),
    "카카오뱅크": (4, 2, 7),
}
LEGAL_DONG = Path(__file__).resolve().parent.parent / "l4/recognizers/legal_dong.txt"
MARK = re.compile(r"\{([A-Z_]+)\}|\[\[(.+?)\|([A-Z_]+)\]\]")


def digits(rng: random.Random, n: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(n))


def rrn_like(rng: random.Random, birth: tuple[int, int, int], code: int, foreign: bool) -> str:
    y, m, d = birth
    body = f"{y % 100:02d}{m:02d}{d:02d}{code}{digits(rng, 5)}"
    s = sum(int(c) * w for c, w in zip(body, [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5], strict=True))
    check = (13 - s % 11) % 10 if foreign else (11 - s % 11) % 10
    return f"{body[:6]}-{body[6:]}{check}"


def brn(rng: random.Random) -> str:
    b = digits(rng, 9)
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(int(c) * x for c, x in zip(b, w, strict=True)) + int(b[8]) * 5 // 10
    v = b + str((10 - s % 10) % 10)
    return f"{v[:3]}-{v[3:5]}-{v[5:]}"


def make_values(rng: random.Random, p: dict[str, Any], dongs: list[str]) -> dict[str, str]:
    age = int(p["age"])
    y = 2026 - age
    birth = (y, rng.randint(1, 12), rng.randint(1, 28))
    male = p["sex"] == "남자"
    native = (1 if male else 2) + (2 if y >= 2000 else 0)
    foreign = (5 if male else 6) + (2 if y >= 2000 else 0)
    prov, _, gu = p["district"].partition("-")
    bank = rng.choice(list(BANKS))
    amount = rng.randrange(10_000, 300_000, 100)
    return {
        "NAME": p["professional_persona"].split(" 씨", 1)[0],
        "PHONE": f"010-0000-{digits(rng, 4)}",
        "EMAIL": f"user{digits(rng, 5)}@example.com",
        "AGE": f"{age}세",
        "DOB": f"{birth[0]}년 {birth[1]}월 {birth[2]}일",
        "RRN": rrn_like(rng, birth, native, foreign=False),
        "FRN": rrn_like(rng, birth, foreign, foreign=True),
        "PASSPORT": "M" + digits(rng, 8),
        "LICENSE": f"{rng.randint(11, 28)}-{rng.randint(10, 26)}-{digits(rng, 6)}-{digits(rng, 2)}",
        "BRN": brn(rng),
        "ORDER_ID": rng.choice(
            [
                f"2026{rng.randint(1, 10):02d}{rng.randint(1, 28):02d}{digits(rng, 6)}",
                f"2026{rng.randint(1, 10):02d}{rng.randint(1, 28):02d}-{digits(rng, 7)}",
            ]
        ),
        "TRACKING": rng.choice([digits(rng, 12), digits(rng, 13)]),
        "CUSTOMER_ID": rng.choice(["cs" + digits(rng, 6), digits(rng, 8), "M" + digits(rng, 8)]),
        "CUSTOMS_ID": "P" + digits(rng, 12),
        "BANK": bank,
        "ACCOUNT": "-".join(digits(rng, n) for n in BANKS[bank]),
        "ADDRESS_ROAD": f"{PROVINCES.get(prov, prov)} {gu} {rng.choice(ROADS)} {rng.randint(1, 300)}",
        "ADDRESS_LOT": f"{rng.choice(dongs)} {rng.randint(1, 999)}-{rng.randint(1, 30)}",
        "ADDRESS_DETAIL": f"{rng.randint(101, 120)}동 {rng.randint(1, 25)}0{rng.randint(1, 4)}호",
        "DATE": f"{rng.randint(1, 10)}월 {rng.randint(1, 28)}일",
        "AMOUNT": f"{amount:,}원",
        "NET": f"{amount - 3000:,}원",
    }


def fill(text: str, values: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    out, gold, pos = [], [], 0
    for m in MARK.finditer(text):
        out.append(text[pos : m.start()])
        start = sum(map(len, out))
        if m.group(1):
            value, etype = values[m.group(1)], SLOT_TYPES.get(m.group(1))
        else:
            value, etype = m.group(2), m.group(3)
        out.append(value)
        if etype:
            gold.append({"start": start, "end": start + len(value), "type": etype, "value": value})
        pos = m.end()
    out.append(text[pos:])
    return "".join(out), gold


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--personas", required=True)
    ap.add_argument(
        "--templates", nargs="+", default=[str(Path(__file__).with_name("templates.yaml"))]
    )
    ap.add_argument("--per-template", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    rng = random.Random(a.seed)  # noqa: S311 - 가상 데이터 생성용
    cols = ["uuid", "professional_persona", "sex", "age", "district"]
    personas = pq.read_table(a.personas, columns=cols).slice(0, 20_000).to_pylist()
    dongs = [w for w in LEGAL_DONG.read_text(encoding="utf-8").split() if len(w) >= 3]
    templates = [
        t for f in a.templates for t in yaml.safe_load(Path(f).read_text(encoding="utf-8"))
    ]

    with open(a.out, "w", encoding="utf-8") as f:
        for t in templates:
            for i in range(a.per_template):
                p = rng.choice(personas)
                v = make_values(rng, p, dongs)
                prompt, gold = fill(t["prompt"].strip(), v)
                rec = {
                    "id": f"{t['id']}-{i}",
                    "group": t.get("group", "template"),
                    "persona_uuid": p["uuid"],
                    "prompt": prompt,
                    "gold_pii": gold,
                    "task": {
                        "type": t["task"]["type"],
                        "reference": fill(t["task"]["reference"], v)[0],
                    },
                    "critical_facts": [
                        {"fact": fill(x["fact"], v)[0], "kind": x["kind"]}
                        for x in t.get("facts", [])
                    ],
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
