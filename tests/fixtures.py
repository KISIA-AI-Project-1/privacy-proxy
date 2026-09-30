"""Synthetic values copied from step7a_analyzer_threshold_semantics.py CASES.
No experimental script is imported; no real personal data is collected.
Compact BRN is the same synthetic digits, testing existing built-in behavior.
"""

from privacy_proxy.schemas import DetectedPII

BRN_VALID = "123-45-67891"
BRN_INVALID = "123-45-67892"
BRN_COMPACT = "1234567891"
PASSPORT = "M123A4567"
PASSPORT_OLD = "M12345678"
LICENSE_VALID = "11-24-123456-01"
LICENSE_INVALID = "99-24-123456-01"
RRN_VALID = "900101-1000006"
RRN_SOFT = "900101-1000007"
FRN_VALID = "900101-5000009"
FRN_SOFT = "900101-5000000"
KEYS = set(DetectedPII.model_fields)
