"""사람 라벨(label_sheet.tsv 마지막 칸)과 lenient 판정의 일치율.

python eval/label_agree.py --data <in.jsonl> --run <run.jsonl> --sheet <label_sheet.tsv>
라벨: 정답 / 오답 / 애매(일치율 분모에서 빼고 건수만 셈). 원본 경로 답변 기준.
"""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from score import task_correct, task_lenient


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--sheet", required=True)
    a = ap.parse_args()
    data = {
        r["id"]: r for r in map(json.loads, Path(a.data).read_text(encoding="utf-8").splitlines())
    }
    rows = {
        r["id"]: r for r in map(json.loads, Path(a.run).read_text(encoding="utf-8").splitlines())
    }
    c: Counter[str] = Counter()
    miss = []
    with open(a.sheet, encoding="utf-8-sig", newline="") as f:
        for line in csv.DictReader(f, delimiter="\t"):
            human = (line.get("라벨(정답/오답)") or "").strip()
            if human not in ("정답", "오답"):
                c["애매·빈칸"] += 1
                continue
            rec, ans = data[line["id"]], rows[line["id"]]["orig_answer"]
            le, unparsed = task_lenient(rec, ans)
            st = task_correct(rec["task"], ans)
            h = human == "정답"
            c["n"] += 1
            c["lenient 일치"] += le == h
            c["strict 일치"] += st == h
            c["lenient unparsed"] += unparsed
            if le != h:
                miss.append((line["id"], human, le, ans[:80].replace("\n", " ")))
    n = c["n"] or 1
    print(f"라벨 {c['n']}건 (애매·빈칸 {c['애매·빈칸']}건 제외)")
    print(f"  lenient 일치 {c['lenient 일치']}/{c['n']} = {c['lenient 일치'] / n:.3f}")
    print(f"  strict  일치 {c['strict 일치']}/{c['n']} = {c['strict 일치'] / n:.3f}")
    print(f"  lenient unparsed {c['lenient unparsed']}건")
    for m in miss:
        print("  불일치:", m)


if __name__ == "__main__":
    main()
