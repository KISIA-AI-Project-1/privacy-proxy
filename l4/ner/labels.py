"""라벨 집합 정의.

라벨 순서를 코드에 박지 않는다. KLUE-NER은 ``O`` 가 마지막(인덱스 12)이라
관례적인 ``O`` = 0 을 가정하면 조용히 어긋난다. 항상 데이터셋 features에서
읽어온다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from l4.ner.bio import OUTSIDE

# KLUE-NER은 6종을 태깅하지만 L4가 실제로 쓰는 것은 인명과 지명뿐이다.
# OG(기관)/DT(날짜)/TI(시각)/QT(수량)은 그 자체로 개인 식별자가 아니다.
# (준식별자 결합 위험은 L5가 따로 판단한다.)
L4_ENTITY_TYPES: tuple[str, ...] = ("PS", "LC")

# 인명 누락은 곧 개인정보 유출이라 별도 지표로 추적한다.
PRIMARY_ENTITY_TYPE = "PS"

# L4가 외부(L5)로 내보내는 최종 entity_type — 형지원과 확정한 엔티티 계약
# (2026-09-08 개정)의 이름이다. 학습·평가·내부 처리(merge_bio_spans,
# arbitrate_josa, metrics.py 등)는 전부 KLUE-NER 라벨("PS"/"LC") 그대로 돈다 —
# 이 매핑은 predict.py의 predict_spans()가 반환하기 직전에만 적용한다. 그전에
# 바꾸면 학습·평가 경로가 이 이름을 모르는 라벨셋과 어긋난다.
L4_ENTITY_TYPE_MAP: dict[str, str] = {
    "PS": "PERSON_KO",
    "LC": "LOCATION_INFORMAL",
}


@dataclass(frozen=True)
class LabelSet:
    """BIO 라벨 이름 목록과 그로부터 파생되는 매핑들."""

    names: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.names:
            raise ValueError("라벨 이름이 비어 있다")
        if OUTSIDE not in self.names:
            raise ValueError(f"{OUTSIDE!r} 라벨이 없다: {self.names}")
        if len(set(self.names)) != len(self.names):
            raise ValueError(f"라벨 이름이 중복된다: {self.names}")

    @property
    def num_labels(self) -> int:
        return len(self.names)

    @property
    def id2label(self) -> dict[int, str]:
        return dict(enumerate(self.names))

    @property
    def label2id(self) -> dict[str, int]:
        return {name: index for index, name in enumerate(self.names)}

    @property
    def outside_id(self) -> int:
        """``O`` 의 인덱스. KLUE-NER에서는 12지만 계산해서 쓴다."""
        return self.names.index(OUTSIDE)

    @property
    def entity_types(self) -> tuple[str, ...]:
        """``B-``/``I-`` 접두사를 뗀 엔티티 타입 목록 (등장 순서 유지)."""
        seen: dict[str, None] = {}
        for name in self.names:
            if name != OUTSIDE:
                seen.setdefault(name.split("-", 1)[1], None)
        return tuple(seen)

    def to_bio(self, ids: list[int]) -> list[str]:
        """라벨 인덱스 시퀀스를 BIO 문자열 시퀀스로."""
        return [self.names[i] for i in ids]


def load_label_set(dataset: Any, split: str = "train") -> LabelSet:
    """데이터셋 features에서 라벨 이름을 읽어 LabelSet을 만든다.

    Args:
        dataset: ``load_dataset("klue/klue", "ner")`` 의 반환값.
        split: features를 읽어올 split. 어느 split이든 동일하다.
    """
    feature = dataset[split].features["ner_tags"].feature
    names = getattr(feature, "names", None)
    if not names:
        raise ValueError("ner_tags가 ClassLabel이 아니다. 데이터셋 구성을 확인할 것")
    return LabelSet(tuple(names))
