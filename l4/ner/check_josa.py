"""조사 경계 확인 — 성능 지표와 별개의 진단 스크립트.

모델이 '김철수에게'를 통째로 인명으로 잡는지, '김철수'만 잡는지 본다.
KLUE-NER 정답은 조사를 제외하지만, 서브워드 토크나이저가 '스타뎀의'처럼
이름과 조사를 한 토큰으로 묶어버리면 모델이 경계를 낼 방법 자체가 없다.

**이 출력이 다음 주 ``alignment/`` (조사 경계 중재) 모듈의 설계 입력이다.**
기존 룰 기반 도구(ko-pii)는 '송하은'을 '송하'로 오분할하는 실패가 있다.
우리는 NER span 경계를 중재 근거로 삼아 이를 개선하려 한다. 그러려면 NER이
경계를 어떻게 내는지부터 실제로 봐야 한다.

    uv run python -m l4.ner.check_josa --model-dir outputs/klue-ner-base-e3/model
"""

from __future__ import annotations

import argparse
from pathlib import Path

from l4.ner.predict import load_model, predict_spans

# 실제 개인정보를 쓰지 않는다. 전부 가상의 이름이다.
TEST_CASES: tuple[str, ...] = (
    "김철수에게 연락해주세요",
    "김철수가 주문한 건",
    "김철수는 환불을 원합니다",
    "송하은 고객님",  # 이름이 조사 모양 음절('은')로 끝난다
    "송하은은 어제 주문했어요",
    "김지은이 문의했습니다",
)

# 이커머스 CS 문맥. P2에서 다룰 표현들이 NER에 어떻게 보이는지 미리 본다.
ECOMMERCE_CASES: tuple[str, ...] = (
    "박민준님 주문번호 20240115-A3F9 환불 요청",
    "이서연 고객이 서울 강남구로 배송지를 바꿔달라고 합니다",
    "최우진씨가 010-0000-0000으로 연락 달라고 하셨어요",
)


def report(model_dir: Path, max_length: int, include_ecommerce: bool) -> None:
    model, tokenizer, label_set = load_model(model_dir)

    groups: list[tuple[str, tuple[str, ...]]] = [("조사 경계", TEST_CASES)]
    if include_ecommerce:
        groups.append(("이커머스 CS 문맥", ECOMMERCE_CASES))

    for title, cases in groups:
        print(f"\n{'=' * 72}\n  {title}\n{'=' * 72}")
        for text in cases:
            spans = predict_spans(text, model, tokenizer, label_set, max_length)
            print(f"\n  입력: {text}")
            if not spans:
                print("    (탐지 없음)")
                continue
            for span in spans:
                # 조사가 span에 딸려 들어갔는지 눈으로 바로 보이게 표시한다
                marker = text[: span.start] + "[" + span.text + "]" + text[span.end :]
                print(
                    f"    ({span.start:>2}, {span.end:>2}) {span.entity_type:<3} "
                    f"{span.text!r:<12} {marker}"
                )


def main() -> None:
    parser = argparse.ArgumentParser(description="NER 조사 경계 확인")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--no-ecommerce", action="store_true")
    args = parser.parse_args()
    report(args.model_dir, args.max_length, include_ecommerce=not args.no_ecommerce)


if __name__ == "__main__":
    main()
