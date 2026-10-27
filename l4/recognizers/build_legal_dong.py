"""국토교통부 전국 법정동 CSV에서 legal_dong.txt를 만든다.

사용: python l4/recognizers/build_legal_dong.py <csv 경로>
읍면동명·리명 중 순한글이면서 동/리로 끝나는 고유 이름만 정렬해 한 줄씩 쓴다.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path


def main(csv_path: str) -> None:
    names: set[str] = set()
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            names.update(row[k].strip() for k in ("읍면동명", "리명"))
    kept = sorted(n for n in names if re.fullmatch(r"[가-힣]+[동리]", n))
    Path(__file__).with_name("legal_dong.txt").write_text("\n".join(kept) + "\n", encoding="utf-8")
    print(len(kept))


if __name__ == "__main__":
    main(sys.argv[1])
