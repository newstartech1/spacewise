"""Safe Bedrock connectivity diagnostic.

By default this makes no inference request. Use --live for one small text-only
Converse request, or --image path/to/room.jpg for one guarded image request.
It deliberately prints neither API keys nor request authorization headers.
"""

import argparse
import os
import ssl
import sys
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, HTTPClientError
from dotenv import load_dotenv


def safe_error_summary(error: BaseException) -> str:
    """Return useful transport context without leaking headers or tokens."""
    cause = error
    for _ in range(5):
        next_cause = getattr(cause, "__cause__", None) or getattr(
            cause, "__context__", None
        )
        if not next_cause:
            break
        cause = next_cause
    return f"{type(error).__name__}; root cause: {type(cause).__name__}: {cause}"


def image_format(path: str) -> str:
    with open(path, "rb") as image_file:
        signature = image_file.read(8)
    if signature.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if signature == b"\x89PNG\r\n\x1a\n":
        return "png"
    raise ValueError("Image must be a JPEG or PNG.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="send one text request")
    parser.add_argument("--image", help="send one JPEG/PNG room-image request")
    args = parser.parse_args()

    load_dotenv(
        dotenv_path=Path(__file__).resolve().parent.parent / "backend" / ".env",
        override=False,
    )
    region = os.getenv("BEDROCK_REGION", "us-east-1")
    model_id = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    token = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "").strip()

    print("SDK bearer-token diagnostic")
    print("token_configured:", bool(token))
    print("region:", region)
    print("model:", model_id)
    print("tls_protocol:", ssl.OPENSSL_VERSION)

    if not token:
        print("RESULT: no request sent; set AWS_BEARER_TOKEN_BEDROCK for this process.")
        return 2
    if not args.live and not args.image:
        print("RESULT: configuration found; no billable request sent (use --live or --image).")
        return 0

    content = [{"text": "Reply with exactly: Spacewise ready"}]
    if args.image:
        with open(args.image, "rb") as image_file:
            image_bytes = image_file.read()
        if len(image_bytes) > 10 * 1024 * 1024:
            raise ValueError("Image must be smaller than 10 MB.")
        content.append(
            {"image": {"format": image_format(args.image), "source": {"bytes": image_bytes}}}
        )

    try:
        client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(connect_timeout=10, read_timeout=60, retries={"max_attempts": 1}),
        )
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": 40, "temperature": 0},
        )
        print("RESULT: SUCCESS")
        print("request_type:", "image" if args.image else "text")
        print("response_received:", bool(response.get("output")))
        return 0
    except ClientError as error:
        print("RESULT: AWS service error:", error.response["Error"].get("Code", "Unknown"))
    except HTTPClientError as error:
        print("RESULT: HTTP/TLS client error:", safe_error_summary(error))
    except BotoCoreError as error:
        print("RESULT: SDK error:", safe_error_summary(error))
    return 1

if __name__ == "__main__":
    sys.exit(main())
