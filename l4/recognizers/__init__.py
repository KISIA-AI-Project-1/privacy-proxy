"""정규식 + 앵커 기반 이커머스 도메인 식별자 인식기.

``l4/ner/`` (NER)와 독립. torch/transformers를 import하지 않는다 — 이 로직만
따로 테스트할 수 있어야 하고, NER 없이도 돌아야 한다.

주소 3종(ADDRESS_ROAD/LOT/DETAIL)은 L3 LOCATION(광역·기초·읍면동 행정구역)과
역할이 다르다 — 도로명·지번·상세주소(동/호/층)만 여기서 담당한다. NER의
LOCATION_INFORMAL(비정형 지명, "강남 쪽에")과도 다르다: 형식이 있으면 정규식,
없으면 모델이 프로젝트 전체 원칙이다.
"""

from l4.recognizers.recognizers import (
    find_account_number,
    find_address_detail,
    find_address_lot,
    find_address_road,
    find_customer_id,
    find_customs_clearance_id,
    find_order_id,
    find_tracking_number,
)

__all__ = [
    "find_account_number",
    "find_address_detail",
    "find_address_lot",
    "find_address_road",
    "find_customer_id",
    "find_customs_clearance_id",
    "find_order_id",
    "find_tracking_number",
]
