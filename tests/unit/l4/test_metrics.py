"""canonicalize의 apply_josa 배선만 확인한다.

조사 판별 로직 자체는 test_alignment.py가 이미 26케이스로 덮는다. 여기서는
metrics.py가 그 결과를 실제로 최종 BIO 시퀀스에 반영하는지만 본다.
"""

from l4.ner.labels import LabelSet
from l4.ner.metrics import canonicalize


def test_apply_josa가_켜지면_예측_span_끝_조사가_잘린다() -> None:
    label_set = LabelSet(("O", "B-PS", "I-PS"))
    text = "송하은은"
    offsets = [(0, 0), (0, 2), (2, 4), (0, 0)]  # [CLS] 송하 ##은은 [SEP]
    label_ids = [0, 1, 2, 0]  # B-PS(송하), I-PS(##은은)

    without = canonicalize(offsets, label_ids, label_set, len(text), text)
    with_josa = canonicalize(offsets, label_ids, label_set, len(text), text, apply_josa=True)

    assert without == ["B-PS", "I-PS", "I-PS", "I-PS"]
    assert with_josa == ["B-PS", "I-PS", "I-PS", "O"]
