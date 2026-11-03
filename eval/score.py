"""run.py 결과를 채점한다. LLM 호출 없음.

python eval/score.py --data <in.jsonl> --run <run.jsonl>

① 왕복: echo 모드에서 복원문 == 원문 비율. GENERALIZE(비가역)가 있는 레코드는 따로 셈.
② 누수: gold 값이 L7 payload에 그대로 있으면 leak. 원인을 셋으로 나눔.
   missed = 탐지 안 됨 / kept = 탐지됐지만 정책상 원문 유지(KEEP·SKIPPED) / partial = 일부만 가려짐
   precision = gold와 겹치는 마스킹 스팬 / 전체 마스킹 스팬(gold가 빠짐없이 표시돼 있다는 전제).

③ Task metric(--l7 real만): 원본 경로 정확도 vs 가명 경로(복원 답변) 정확도.
   분류 = 답변이 정답으로 시작 / QA = 숫자 정답은 포함, 아니면 시작 / 추출 = 정답 값 전부 포함.
   utility loss = 원본 - 가명. paired 클러스터 bootstrap CI + McNemar exact.
   strict(위 규칙)와 lenient(choices.yaml 기반 단계적 추출)를 같이 냄. lenient:
     선택지 템플릿 = ① `결과:`/`정답:`/`답:` 뒤·**강조** 안 → ② 첫 문장 → ③ 마지막 줄에서
       선택지가 하나만 남으면 그것. 선택지 바로 뒤 부정(않·아니·없)은 이지선다면 반대로, 아니면 버림.
       못 정하면 unparsed(오답, 건수 따로).
     value: number = 같은 단계로 숫자가 하나만 남으면 정답 숫자와 대조 / value: contains = 정규화 포함.
   --masked: 같은 스팬을 ***로 지운 프롬프트의 답변(masked_star)과 원본 비교.
④ CFP(--l7 real만): 핵심 사실이 답변에 남은 비율(공백·문장부호 무시 포함 검사).
   값형(숫자·gold 값) / 서술형으로 나눔. 서술형은 문자열 검사라 과소 측정될 수 있음.

CI: 클러스터(=템플릿) bootstrap 95%가 주, Wilson은 참고.
"""

import argparse
import json
import math
import random
import re
from collections import defaultdict
from math import comb
from pathlib import Path
from typing import Any

import yaml

CHANGED = {"TOKENIZE", "GENERALIZE"}
CHOICES: dict[str, Any] = yaml.safe_load(
    (Path(__file__).with_name("choices.yaml")).read_text(encoding="utf-8")
)
ALIAS = {"예": ["예", "네"], "아니오": ["아니오", "아니요"]}
NEG = re.compile(r"[가-힣]{0,3}\s?(?:않|아니|아닙|아님|없)")
MARKED = re.compile(r"(?:결과|정답|답변|답)\s*[:\uff1a]\s*([^\n]*)|\*\*(.+?)\*\*")


def wilson(k: int, n: int, z: float = 1.96) -> str:
    if n == 0:
        return "-"
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return f"{k}/{n} = {p:.3f} wilson[{max(0, c - h):.3f}, {min(1, c + h):.3f}]"


def cluster_ci(hits: list[tuple[str, bool]], reps: int = 2000) -> str:
    """비율 + 클러스터 bootstrap 95% CI + Wilson(참고)."""
    by: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for c, h in hits:
        by[c][0] += h
        by[c][1] += 1
    groups = list(by.values())
    k, n = sum(g[0] for g in groups), sum(g[1] for g in groups)
    if n == 0:
        return "-"
    rng = random.Random(0)  # noqa: S311
    stats = []
    for _ in range(reps):
        sample = rng.choices(groups, k=len(groups))
        sn = sum(g[1] for g in sample)
        stats.append(sum(g[0] for g in sample) / sn)
    stats.sort()
    lo, hi = stats[int(reps * 0.025)], stats[int(reps * 0.975) - 1]
    return f"{wilson(k, n)}  boot[{lo:.3f}, {hi:.3f}] (클러스터 {len(groups)})"


def paired(pairs: list[tuple[str, bool, bool]], reps: int = 2000) -> str:
    """(클러스터, 원본 맞음, 가명 맞음) → 두 정확도, 차이 CI, McNemar p."""
    if not pairs:
        return "-"
    n = len(pairs)
    ao, ap = sum(o for _, o, _ in pairs) / n, sum(q for _, _, q in pairs) / n
    by: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    for cl, o, q in pairs:
        by[cl].append((o, q))
    groups = list(by.values())
    rng = random.Random(0)  # noqa: S311
    diffs: list[float] = []
    for _ in range(reps):
        sample = [x for g in rng.choices(groups, k=len(groups)) for x in g]
        diffs.append(sum(o - q for o, q in sample) / len(sample))
    diffs.sort()
    b = sum(1 for _, o, q in pairs if o and not q)
    c = sum(1 for _, o, q in pairs if q and not o)
    pv = min(1.0, 2 * sum(comb(b + c, i) for i in range(min(b, c) + 1)) / 2 ** (b + c))
    return (
        f"원본 {ao:.3f} / 가명 {ap:.3f} (n={n})  loss {ao - ap:+.3f} "
        f"boot[{diffs[int(reps * 0.025)]:+.3f}, {diffs[int(reps * 0.975) - 1]:+.3f}]  "
        f"McNemar 원본만맞음={b} 가명만맞음={c} p={pv:.3f}"
    )


def norm(s: str) -> str:
    return re.sub(r"[\s\"'`.,!?:;()\[\]{}<>~*·]", "", s)


def task_correct(task: dict[str, Any], answer: str) -> bool | None:
    kind, ref = task["type"], task["reference"]
    if kind == "자유서술" or not ref:
        return None
    a = norm(answer)
    if kind == "추출":
        try:
            parsed = json.loads(ref)
            values = list(parsed.values()) if isinstance(parsed, dict) else [ref]
        except json.JSONDecodeError:
            values = [ref]
        return all(norm(str(v)) in a for v in values)
    if kind == "QA" and any(ch.isdigit() for ch in ref):
        return norm(ref) in a
    return a.startswith(norm(ref))


def _choice_mentions(text: str, opts: list[str]) -> set[str]:
    surf = {a: o for o in opts for a in ALIAS.get(o, [o])}
    pat = re.compile("|".join(re.escape(x) for x in sorted(surf, key=len, reverse=True)))
    found: set[str] = set()
    for m in pat.finditer(text):
        w = m.group(0)
        if len(w) == 1 and (
            re.match(r"[가-힣]", text[m.start() - 1 : m.start()] or " ")
            or (
                re.match(r"[가-힣]", text[m.end() : m.end() + 1] or " ")
                and not re.match(r"(입|이|으|에|레|단)", text[m.end() : m.end() + 1])
            )
        ):
            continue  # 한 글자 선택지(상/중/하·네)는 단어 일부면 무시
        o = surf[w]
        if NEG.match(text, m.end()):
            if len(opts) != 2:
                continue
            o = opts[1 - opts.index(o)]
        found.add(o)
    return found


def _numbers(text: str) -> set[str]:
    return {x.replace(",", "") for x in re.findall(r"\d[\d,]*", text)}


def _staged(answer: str, pick: Any) -> set[str] | None:
    """표지 → 첫 문장 → 마지막 줄 순서로 후보가 하나만 남는 단계를 찾는다."""
    marked = " ".join(a or b for a, b in MARKED.findall(answer))
    lines = [x for x in answer.splitlines() if x.strip()]
    first = re.split(r"(?<=[.!?。])\s|\n", answer.strip(), maxsplit=1)[0]
    for seg in (marked, first, lines[-1] if lines else ""):
        got = pick(seg) if seg else set()
        if len(got) == 1:
            return got
    return None


def task_lenient(rec: dict[str, Any], answer: str) -> tuple[bool | None, bool]:
    """(정답 여부, unparsed 여부). choices.yaml에 없으면 strict."""
    task = rec["task"]
    spec = CHOICES.get(rec["id"].rsplit("-", 1)[0])
    if spec is None or task["type"] not in ("분류", "QA"):
        return task_correct(task, answer), False
    if isinstance(spec, list):
        got = _staged(answer, lambda t: _choice_mentions(t, spec))
        return (got == {task["reference"]}) if got else False, got is None
    if spec["value"] == "number":
        got = _staged(answer, _numbers)
        return (got == _numbers(task["reference"])) if got else False, got is None
    return norm(task["reference"]) in norm(answer), False


def fact_kept(fact: str, rec: dict[str, Any], answer: str, lenient: bool = False) -> bool:
    task = rec["task"]
    if fact == task["reference"] and task["type"] in ("분류", "QA"):
        return bool(task_lenient(rec, answer)[0] if lenient else task_correct(task, answer))
    return norm(fact) in norm(answer)


def gold_status(g: dict[str, Any], outcomes: list[dict[str, Any]], payload: str) -> str:
    span = set(range(g["start"], g["end"]))
    changed = set().union(
        *(range(o["start_idx"], o["end_idx"]) for o in outcomes if o["action"] in CHANGED)
    )
    touched = any(o["start_idx"] < g["end"] and g["start"] < o["end_idx"] for o in outcomes)
    if span <= changed:
        return "protected" if g["value"] not in payload else "leak_elsewhere"
    if span & changed:
        return "partial"
    return "kept" if touched else "missed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--masked", help="masked.py 결과(masked_star 답변)")
    a = ap.parse_args()

    data = {
        r["id"]: r for r in map(json.loads, Path(a.data).read_text(encoding="utf-8").splitlines())
    }
    rows = [json.loads(line) for line in Path(a.run).read_text(encoding="utf-8").splitlines()]
    runs = list({r["id"]: r for r in rows}.values())  # 재실행으로 덧붙은 행은 마지막 것만
    m = runs[0]
    print(f"commit={m['commit']} l7={m['l7']} ner={m['ner']} n={len(runs)}")

    failed = [r["id"] for r in runs if r["status"] != "success"]
    print(f"파이프라인 실패: {len(failed)} {failed[:5]}")

    rt: dict[tuple[str, str], list[tuple[str, bool]]] = defaultdict(list)
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_group: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    prec: dict[str, list[tuple[str, bool]]] = defaultdict(list)
    for r in runs:
        if r["status"] != "success":
            continue
        rec = data[r["id"]]
        cl = rec["id"].rsplit("-", 1)[0]
        lossy = any(o["action"] == "GENERALIZE" for o in r["outcomes"])
        rt[(rec["group"], "비가역 포함" if lossy else "가역만")].append(
            (cl, r["restored"] == rec["prompt"])
        )
        for g in rec["gold_pii"]:
            s = gold_status(g, r["outcomes"], r["payload"] or "")
            by_type[g["type"]][s] += 1
            by_group[rec["group"]].append((cl, s == "protected"))
        for o in r["outcomes"]:
            if o["action"] in CHANGED:
                hit = any(
                    o["start_idx"] < g["end"] and g["start"] < o["end_idx"] for g in rec["gold_pii"]
                )
                prec[rec["group"]].append((cl, hit))

    if m["l7"] == "echo":
        print("\n① 왕복 정확도 (복원문 == 원문)")
        for (grp, kind), v in sorted(rt.items()):
            print(f"  {grp:<18} {kind:<8} {cluster_ci(v)}")

    print("\n② gold PII 보호율 (값이 payload에서 사라짐)")
    for grp, v in sorted(by_group.items()):
        print(f"  {grp:<18} {cluster_ci(v)}")
    print("\n② 마스킹 precision (gold와 겹치는 마스킹 스팬 / 전체 마스킹 스팬)")
    for grp, v in sorted(prec.items()):
        print(f"  {grp:<18} {cluster_ci(v)}")
    if m["l7"] == "real":
        masked = {}
        if a.masked:
            for line in Path(a.masked).read_text(encoding="utf-8").splitlines():
                x = json.loads(line)
                if x["masked_status"] == "success":
                    masked[x["id"]] = x["masked_answer"]
        report_utility(runs, data, masked)
    cols = ["n", "protected", "missed", "kept", "partial", "leak_elsewhere"]
    print(f"\n  {'type':<22}" + "".join(f"{c:>15}" for c in cols))
    for t, c in sorted(by_type.items()):
        c["n"] = sum(c.values())
        print(f"  {t:<22}" + "".join(f"{c[k]:>15}" for k in cols))


def report_utility(
    runs: list[dict[str, Any]], data: dict[str, Any], masked: dict[str, str]
) -> None:
    pairs_t = dict[tuple[str, str], list[tuple[str, bool, bool]]]
    task: dict[str, pairs_t] = {k: defaultdict(list) for k in ("strict", "lenient", "masked")}
    facts: dict[str, pairs_t] = {k: defaultdict(list) for k in ("strict", "lenient", "masked")}
    unparsed: dict[str, int] = defaultdict(int)
    skipped = 0
    for r in runs:
        if r["restored"] is None or r.get("orig_answer") is None:
            skipped += 1
            continue
        rec = data[r["id"]]
        cl = rec["id"].rsplit("-", 1)[0]
        grp, kind = rec["group"], rec["task"]["type"]
        answers = {"가명": r["restored"], "masked": masked.get(r["id"])}
        for mode, other in (("strict", "가명"), ("lenient", "가명"), ("masked", "masked")):
            ans = answers[other]
            if ans is None:
                continue
            le = mode != "strict"
            if le:
                ok_o, up_o = task_lenient(rec, r["orig_answer"])
                ok_p, up_p = task_lenient(rec, ans)
                unparsed[f"{mode}/원본"] += up_o
                unparsed[f"{mode}/{other}"] += up_p
            else:
                ok_o, ok_p = (
                    task_correct(rec["task"], r["orig_answer"]),
                    task_correct(rec["task"], ans),
                )
            if ok_o is not None and ok_p is not None:
                task[mode][(grp, kind)].append((cl, ok_o, ok_p))
                task[mode][(grp, "전체")].append((cl, ok_o, ok_p))
            golds = {g["value"] for g in rec["gold_pii"]}
            for f in rec["critical_facts"]:
                isval = f["fact"] in golds or any(ch.isdigit() for ch in f["fact"])
                pair = (
                    cl,
                    fact_kept(f["fact"], rec, r["orig_answer"], le),
                    fact_kept(f["fact"], rec, ans, le),
                )
                facts[mode][(grp, f"{f['kind']}/{'값형' if isval else '서술형'}")].append(pair)
                facts[mode][(grp, "전체")].append(pair)
    print(f"\n③ Task metric (한쪽 경로라도 실패한 레코드 {skipped}건 제외)")
    for mode, label in (
        ("strict", "strict, 원본 vs 가명"),
        ("lenient", "lenient, 원본 vs 가명"),
        ("masked", "lenient, 원본 vs masked_star(오른쪽 값이 masked)"),
    ):
        if task[mode]:
            print(f"  [{label}]")
        for (grp, kind), v in sorted(task[mode].items()):
            print(f"  {grp:<18} {kind:<6} {paired(v)}")
    print(f"  lenient unparsed(오답 처리): {dict(unparsed)}")
    print("\n④ Critical Fact Preservation (원본 답변 / 비교 답변에 사실이 남은 비율)")
    for mode, label in (
        ("lenient", "원본 vs 가명(복원)"),
        ("masked", "원본 vs masked_star"),
    ):
        if facts[mode]:
            print(f"  [{label}]")
        for (grp, kind), v in sorted(facts[mode].items()):
            print(f"  {grp:<18} {kind:<18} {paired(v)}")


if __name__ == "__main__":
    main()
