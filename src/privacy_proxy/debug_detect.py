import os
import sys
import traceback

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, "../.."))
src_dir = os.path.join(root_dir, "src")

sys.path.insert(0, root_dir)
sys.path.insert(0, src_dir)

from l4.recognizers import (  # noqa: E402
    find_customer_id,
    find_customs_clearance_id,
    find_order_id,
    find_tracking_number,
)

from privacy_proxy.pipeline import _get_l3_service, _to_detected_pii  # noqa:E402

TEXT = "안녕하세요 제 번호는 010-9999-8888이고 이메일은 test@example.com입니다."

print("=== L3 ===")
try:
    results = _get_l3_service().analyze(raw_prompt=TEXT, segment_id="seg-1")
    print("L3 결과 개수:", len(results))
    for det in results:
        print("  타입:", type(det).__name__)
        _to_detected_pii(det, 0)
    print("L3 통과")
except Exception:
    traceback.print_exc()

print("=== L4 ===")
try:
    for finder in (
        find_customer_id,
        find_customs_clearance_id,
        find_order_id,
        find_tracking_number,
    ):
        for det in finder(TEXT):
            print("  타입:", type(det).__name__)
            _to_detected_pii(det, 0)
    print("L4 통과")
except Exception:
    traceback.print_exc()
