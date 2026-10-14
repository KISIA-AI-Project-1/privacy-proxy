"""Runtime regression contract for KR_DRIVER_LICENSE ASCII boundaries."""

import unittest

from l4.recognizers import find_customs_clearance_id, find_tracking_number

from privacy_proxy.l3.service import L3AnalyzerService
from privacy_proxy.schemas import DetectionTier
from tests.fixtures import LICENSE_VALID


class DriverLicenseBoundaryRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = L3AnalyzerService()

    def detect(self, raw_prompt: str):
        return self.service.analyze(
            raw_prompt,
            "driver-license-boundary",
            entities=["KR_DRIVER_LICENSE"],
        )

    def test_ascii_identifier_adjacent_values_are_not_driver_license(self):
        cases = (
            # L4 CUSTOMS_CLEARANCE_ID shape: P + 12 digits.
            "P123456789012",
            "p123456789012",
            # General ASCII identifier contamination.
            "A123456789012",
            "X123456789012Y",
            "DL11-24-123456-01",
            "11-24-123456-01A",
        )

        for raw_prompt in cases:
            with self.subTest(raw_prompt=raw_prompt):
                self.assertEqual(
                    self.detect(raw_prompt),
                    [],
                    msg=(
                        "KR_DRIVER_LICENSE must not consume a numeric "
                        "substring embedded in an ASCII identifier"
                    ),
                )

    def test_existing_legitimate_license_surfaces_are_preserved(self):
        cases = (
            LICENSE_VALID,
            f"({LICENSE_VALID})",
            "\uba74\ud5c8\ubc88\ud638" + LICENSE_VALID,
            LICENSE_VALID + "\uc785\ub2c8\ub2e4",
        )

        for raw_prompt in cases:
            with self.subTest(raw_prompt=raw_prompt):
                detections = self.detect(raw_prompt)

                self.assertEqual(len(detections), 1)

                detection = detections[0]

                self.assertEqual(
                    detection.original_value,
                    LICENSE_VALID,
                )
                self.assertEqual(
                    raw_prompt[detection.start_idx : detection.end_idx],
                    LICENSE_VALID,
                )
                self.assertEqual(
                    detection.source,
                    "KrDriverLicenseRecognizer",
                )
                self.assertIs(
                    detection.tier,
                    DetectionTier.DETERMINISTIC,
                )
                self.assertIsNone(detection.confidence)

    def test_l3_l4_ownership_split_is_preserved(self):
        customs_cases = (
            "P123456789012",
            "P123456789012 \ud655\uc778\ud574\uc8fc\uc138\uc694",
            ("\uac1c\uc778\ud1b5\uad00\uace0\uc720\ubd80\ud638 P123456789012 \uc785\ub2c8\ub2e4"),
        )

        for raw_prompt in customs_cases:
            with self.subTest(
                owner="CUSTOMS_CLEARANCE_ID",
                raw_prompt=raw_prompt,
            ):
                l3_results = self.detect(raw_prompt)

                l4_results = find_customs_clearance_id(
                    raw_prompt,
                    segment_id="driver-license-boundary",
                )

                self.assertEqual(l3_results, [])
                self.assertEqual(len(l4_results), 1)

                detection = l4_results[0]

                entity_type = getattr(
                    detection.entity_type,
                    "value",
                    detection.entity_type,
                )

                self.assertEqual(
                    entity_type,
                    "CUSTOMS_CLEARANCE_ID",
                )
                self.assertEqual(
                    detection.original_value,
                    "P123456789012",
                )
                self.assertEqual(
                    detection.normalized,
                    "P123456789012",
                )
                self.assertEqual(
                    raw_prompt[detection.start_idx : detection.end_idx],
                    "P123456789012",
                )
                self.assertEqual(
                    detection.source,
                    "L4_RECOGNIZER_CUSTOMS",
                )
                self.assertIs(
                    detection.tier,
                    DetectionTier.RULE_ANCHORED,
                )

        license_cases = (
            LICENSE_VALID,
            ("\uba74\ud5c8\ubc88\ud638" + LICENSE_VALID + "\uc785\ub2c8\ub2e4"),
        )

        for raw_prompt in license_cases:
            with self.subTest(
                owner="KR_DRIVER_LICENSE",
                raw_prompt=raw_prompt,
            ):
                l3_results = self.detect(raw_prompt)

                l4_results = find_customs_clearance_id(
                    raw_prompt,
                    segment_id="driver-license-boundary",
                )

                self.assertEqual(len(l3_results), 1)
                self.assertEqual(l4_results, [])

                detection = l3_results[0]

                self.assertEqual(
                    detection.entity_type,
                    "KR_DRIVER_LICENSE",
                )
                self.assertEqual(
                    detection.original_value,
                    LICENSE_VALID,
                )
                self.assertEqual(
                    raw_prompt[detection.start_idx : detection.end_idx],
                    LICENSE_VALID,
                )


class DriverLicenseCompactContextRuntimeTests(unittest.TestCase):
    """Compact license ambiguity regression contract."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.service = L3AnalyzerService()

    def detect(self, raw_prompt: str):
        return self.service.analyze(
            raw_prompt,
            "driver-license-compact-context",
            entities=["KR_DRIVER_LICENSE"],
        )

    def test_bare_compact_is_not_driver_license(self):
        self.assertEqual(
            self.detect("112412345601"),
            [],
        )

    def test_compact_requires_explicit_license_context(
        self,
    ):
        value = "112412345601"

        cases = (
            f"면허번호 {value}",
            f"운전면허번호 {value}",
            f"{value} 운전면허번호입니다",
        )

        for raw_prompt in cases:
            with self.subTest(
                raw_prompt=raw_prompt,
            ):
                detections = self.detect(raw_prompt)

                self.assertEqual(
                    len(detections),
                    1,
                )

                detection = detections[0]

                self.assertEqual(
                    detection.entity_type,
                    "KR_DRIVER_LICENSE",
                )

                self.assertEqual(
                    detection.original_value,
                    value,
                )

                self.assertEqual(
                    raw_prompt[detection.start_idx : detection.end_idx],
                    value,
                )

                self.assertIs(
                    detection.tier,
                    DetectionTier.DETERMINISTIC,
                )

                self.assertIsNone(detection.confidence)

    def test_service_identifier_contexts_do_not_emit_driver(
        self,
    ):
        value = "112412345601"

        cases = (
            f"송장번호 {value}",
            f"운송장번호 {value}",
            f"택배번호 {value}",
            f"주문번호 {value}",
            f"고객번호 {value}",
            f"({value})",
            f"P{value}",
        )

        for raw_prompt in cases:
            with self.subTest(
                raw_prompt=raw_prompt,
            ):
                self.assertEqual(
                    self.detect(raw_prompt),
                    [],
                )

    def test_space_separated_license_is_preserved(
        self,
    ):
        value = "11 24 123456 01"

        detections = self.detect(value)

        self.assertEqual(
            len(detections),
            1,
        )

        self.assertEqual(
            detections[0].original_value,
            value,
        )

        self.assertIs(
            detections[0].tier,
            DetectionTier.DETERMINISTIC,
        )

    def test_tracking_context_remains_l4_owned(
        self,
    ):
        raw_prompt = "송장번호 112412345601"

        self.assertEqual(
            self.detect(raw_prompt),
            [],
        )

        tracking = find_tracking_number(
            raw_prompt,
            segment_id=("driver-license-compact-context"),
        )

        self.assertEqual(
            len(tracking),
            1,
        )

        self.assertEqual(
            tracking[0].entity_type,
            "TRACKING_NUMBER",
        )

        self.assertEqual(
            tracking[0].original_value,
            "112412345601",
        )


if __name__ == "__main__":
    unittest.main()
