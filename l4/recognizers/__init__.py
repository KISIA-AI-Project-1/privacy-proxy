"""정규식 + 앵커 기반 이커머스 도메인 식별자 인식기.

``l4/ner/`` (NER)와 독립. torch/transformers를 import하지 않는다 — 이 로직만
따로 테스트할 수 있어야 하고, NER 없이도 돌아야 한다.

주소(ADDRESS_ROAD/LOT/DETAIL)는 여기 없다. L3의 LOCATION Normalizer 레이어
인터페이스 확정 후 별도로 붙인다.
"""

from l4.recognizers.recognizers import (
    find_customer_id,
    find_customs_clearance_id,
    find_order_id,
    find_tracking_number,
)

__all__ = [
    "find_customer_id",
    "find_customs_clearance_id",
    "find_order_id",
    "find_tracking_number",
]
