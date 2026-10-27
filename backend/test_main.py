import unittest
from unittest.mock import patch

from backend.main import (
    bedrock_is_configured,
    combine_recommendations,
    health,
    parse_bedrock_json,
)


class BedrockIntegrationHelpersTests(unittest.TestCase):
    def test_combines_local_and_semantic_recommendations_without_duplicates(self):
        self.assertEqual(
            combine_recommendations(
                ["Keep a clear path.", "Use layered lighting."],
                ["keep a clear path.", "Move the chair away from the doorway."],
            ),
            [
                "Keep a clear path.",
                "Use layered lighting.",
                "Move the chair away from the doorway.",
            ],
        )

    def test_parses_fenced_model_json(self):
        self.assertEqual(
            parse_bedrock_json("```json\n{\"recommendations\": [\"Open curtains\"]}\n```"),
            {"recommendations": ["Open curtains"]},
        )

    def test_health_reports_bedrock_ready_only_with_complete_configuration(self):
        with patch.dict(
            "os.environ",
            {
                "AWS_BEARER_TOKEN_BEDROCK": "test-token-not-a-real-secret",
                "BEDROCK_MODEL_ID": "amazon.nova-lite-v1:0",
                "BEDROCK_REGION": "us-east-1",
            },
            clear=False,
        ):
            self.assertTrue(bedrock_is_configured())
            self.assertTrue(health()["bedrock_configured"])


if __name__ == "__main__":
    unittest.main()
