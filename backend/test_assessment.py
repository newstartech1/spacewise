import unittest

from backend.assessment import build_assessment


class AssessmentTests(unittest.TestCase):
    def test_missing_analysis_uses_documented_fixed_baselines(self):
        assessment = build_assessment("Overall improvement", {}, [])

        self.assertEqual(assessment["scores"]["design_confidence"], 37)
        self.assertEqual(assessment["scores"]["space_utilization"], 50)
        self.assertEqual(assessment["scores"]["budget_compatibility"], 60)
        self.assertEqual(assessment["scores"]["feasibility_confidence"], 55)
        self.assertEqual(assessment["scores"]["overall_compatibility"], 49)

    def test_same_inputs_always_produce_same_bounded_scores(self):
        analysis = {
            "detected_inventory": [
                {"name": "Desk", "confidence": 92, "instances": 1},
                {"name": "Chair", "confidence": 80, "instances": 2},
            ],
            "image_properties": {"quality": {"sharpness": 65, "contrast": 70}},
        }
        first = build_assessment("More floor space, Better workspace", analysis, ["One"])
        second = build_assessment("More floor space, Better workspace", analysis, ["One"])

        self.assertEqual(first, second)
        self.assertTrue(all(0 <= score <= 100 for score in first["scores"].values()))


if __name__ == "__main__":
    unittest.main()
