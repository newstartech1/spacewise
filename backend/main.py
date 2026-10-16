import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import urllib.request
import urllib.error

from backend.assessment import build_assessment


logger = logging.getLogger(__name__)


app = FastAPI(
    title="Spacewise API",
    description="Minimal API foundation for the Spacewise hackathon MVP.",
    version="0.1.0",
)

LOCAL_FRONTEND_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=LOCAL_FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "Spacewise API is running",
    }


@app.post("/analyze-room")
async def analyze_room(
    goal: str = Form(...),
    photo: UploadFile = File(...),
) -> dict[str, Any]:
    if not photo.content_type or not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")

    bucket_name = os.getenv("SPACEWISE_S3_BUCKET")
    if not bucket_name:
        raise HTTPException(
            status_code=503,
            detail="Missing SPACEWISE_S3_BUCKET. Configure an existing S3 bucket before analysis.",
        )

    apertus_api_key = os.getenv("APERTUS_API_KEY")

    image_bytes = await photo.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")

    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Please upload an image under 10 MB.")

    s3_key = _build_s3_key(photo.filename)
    s3_client = _aws_client("s3")

    _verify_bucket_exists(s3_client, bucket_name)
    bucket_region = _get_bucket_region(s3_client, bucket_name)
    rekognition_client = _aws_client("rekognition", region_name=bucket_region)
    _upload_to_s3(s3_client, bucket_name, s3_key, image_bytes, photo.content_type)
    rekognition_analysis = _analyze_with_rekognition(
        rekognition_client,
        bucket_name,
        s3_key,
    )
    apertus_analysis = (
        _analyze_with_apertus(
            api_key=apertus_api_key,
            selected_goal=goal,
            rekognition_analysis=rekognition_analysis,
        )
        if apertus_api_key
        else _deterministic_analysis_without_apertus(goal, rekognition_analysis)
    )
    assessment = build_assessment(goal, rekognition_analysis, apertus_analysis["recommendations"])

    return {
        "selected_goal": goal,
        "storage": {
            "bucket": bucket_name,
            "key": s3_key,
        },
        "detected_inventory": rekognition_analysis["detected_inventory"],
        "image_properties": rekognition_analysis["image_properties"],
        "recommendations": apertus_analysis.get("recommendations", []),
        "limitations": apertus_analysis.get("limitations", []),
        "detected_facts": apertus_analysis.get("detected_facts", []),
        "assessment": assessment,
    }


def _aws_client(service_name: str, region_name: str | None = None):
    region_name = region_name or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    session = boto3.session.Session(region_name=region_name)
    return session.client(service_name)


def _build_s3_key(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    return f"room-uploads/{uuid.uuid4().hex}{suffix}"


def _verify_bucket_exists(s3_client, bucket_name: str) -> None:
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except NoCredentialsError as exc:
        raise HTTPException(
            status_code=503,
            detail="AWS credentials were not found. Configure the local AWS CLI or environment.",
        ) from exc
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchBucket", "NotFound"}:
            detail = f"S3 bucket '{bucket_name}' does not exist. Create or configure an existing bucket."
        elif error_code in {"403", "AccessDenied"}:
            detail = f"Access denied for S3 bucket '{bucket_name}'. Check AWS credentials and bucket permissions."
        else:
            detail = f"Could not verify S3 bucket '{bucket_name}': {error_code or 'unknown AWS error'}."
        raise HTTPException(status_code=503, detail=detail) from exc
    except BotoCoreError as exc:
        raise HTTPException(status_code=503, detail="Could not connect to AWS S3.") from exc


def _get_bucket_region(s3_client, bucket_name: str) -> str:
    try:
        location = s3_client.get_bucket_location(Bucket=bucket_name).get("LocationConstraint")
    except ClientError as exc:
        raise HTTPException(
            status_code=503,
            detail="Could not determine the S3 bucket region required for Amazon Rekognition.",
        ) from exc
    except BotoCoreError as exc:
        raise HTTPException(status_code=503, detail="Could not connect to AWS S3.") from exc

    # S3 represents us-east-1 as null and retained "EU" for its legacy region name.
    if location is None:
        return "us-east-1"
    if location == "EU":
        return "eu-west-1"
    return str(location)


def _upload_to_s3(
    s3_client,
    bucket_name: str,
    s3_key: str,
    image_bytes: bytes,
    content_type: str,
) -> None:
    try:
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=image_bytes,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )
    except ClientError as exc:
        raise HTTPException(status_code=503, detail="Could not upload image to S3.") from exc
    except BotoCoreError as exc:
        raise HTTPException(status_code=503, detail="Could not connect to AWS S3.") from exc


def _analyze_with_rekognition(
    rekognition_client,
    bucket_name: str,
    s3_key: str,
) -> dict[str, Any]:
    image = {"S3Object": {"Bucket": bucket_name, "Name": s3_key}}
    try:
        response = rekognition_client.detect_labels(
            Image=image,
            MaxLabels=75,
            MinConfidence=55,
            Features=["GENERAL_LABELS", "IMAGE_PROPERTIES"],
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "InvalidParameterException":
            _log_rekognition_client_error(exc, rekognition_client, "DetectLabels with image properties")
            try:
                response = rekognition_client.detect_labels(
                    Image=image,
                    MaxLabels=75,
                    MinConfidence=55,
                )
            except ClientError as fallback_exc:
                _log_rekognition_client_error(fallback_exc, rekognition_client, "DetectLabels fallback")
                raise HTTPException(
                    status_code=503,
                    detail="Amazon Rekognition could not analyze the uploaded image.",
                ) from fallback_exc
        else:
            _log_rekognition_client_error(exc, rekognition_client, "DetectLabels with image properties")
            raise HTTPException(
                status_code=503,
                detail="Amazon Rekognition could not analyze the uploaded image.",
            ) from exc
    except BotoCoreError as exc:
        raise HTTPException(status_code=503, detail="Could not connect to Amazon Rekognition.") from exc

    return {
        "detected_inventory": _extract_room_inventory(response.get("Labels", [])),
        "image_properties": _extract_image_properties(response.get("ImageProperties", {})),
    }


def _log_rekognition_client_error(exc: ClientError, rekognition_client, operation: str) -> None:
    error_code = str(exc.response.get("Error", {}).get("Code", "unknown"))
    region_name = getattr(rekognition_client.meta, "region_name", "unknown")
    logger.warning(
        "Rekognition request failed: operation=%s error_code=%s region=%s",
        operation,
        error_code,
        region_name,
    )


def _extract_room_inventory(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    useful_terms = {
        "appliance",
        "bed",
        "bedroom",
        "bookcase",
        "cabinet",
        "chair",
        "couch",
        "curtain",
        "desk",
        "dining table",
        "door",
        "electronics",
        "furniture",
        "home decor",
        "indoor",
        "lamp",
        "lighting",
        "living room",
        "monitor",
        "office",
        "pillow",
        "plant",
        "rug",
        "screen",
        "shelf",
        "table",
        "television",
        "window",
    }

    inventory = []
    for label in labels:
        name = label.get("Name", "")
        related_names = {
            name.lower(),
            *(parent.get("Name", "").lower() for parent in label.get("Parents", [])),
            *(category.get("Name", "").lower() for category in label.get("Categories", [])),
        }
        if not related_names.intersection(useful_terms):
            continue

        inventory.append(
            {
                "name": name,
                "confidence": round(float(label.get("Confidence", 0)), 1),
                "instances": len(label.get("Instances", [])),
                "parents": [parent.get("Name") for parent in label.get("Parents", []) if parent.get("Name")],
                "categories": [
                    category.get("Name")
                    for category in label.get("Categories", [])
                    if category.get("Name")
                ],
            }
        )

    return inventory[:30]


def _extract_image_properties(image_properties: dict[str, Any]) -> dict[str, Any]:
    quality = image_properties.get("Quality", {})
    dominant_colors = image_properties.get("DominantColors", [])
    return {
        "quality": {
            "brightness": _rounded_or_none(quality.get("Brightness")),
            "sharpness": _rounded_or_none(quality.get("Sharpness")),
            "contrast": _rounded_or_none(quality.get("Contrast")),
        },
        "dominant_colors": [
            {
                "hex": color.get("HexCode"),
                "pixel_percent": _rounded_or_none(color.get("PixelPercent")),
            }
            for color in dominant_colors[:5]
        ],
        "note": "Image properties are approximate and do not provide exact room dimensions or geometry.",
    }


def _rounded_or_none(value: Any) -> float | None:
    if value is None:
        return None
    return round(float(value), 1)


def _analyze_with_apertus(api_key: str, selected_goal: str, rekognition_analysis: dict[str, Any]) -> dict[str, Any]:
    base_url = os.getenv("APERTUS_BASE_URL", "").rstrip("/")
    model = os.getenv("APERTUS_MODEL", "")
    if not base_url.startswith("https://") or not model:
        raise HTTPException(status_code=503, detail="Configure HTTPS APERTUS_BASE_URL and APERTUS_MODEL.")
    prompt = {
        "goal": selected_goal,
        "rekognition_analysis": rekognition_analysis,
        "instructions": [
            "Recommend practical improvements for an existing room.",
            "Do not invent objects not supported by detected inventory.",
            "Do not claim exact dimensions or geometry from one photo.",
            "Return only JSON with arrays: detected_facts, recommendations, limitations.",
        ],
    }
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a careful room improvement analyst. Reply with JSON only."},
            {"role": "user", "content": json.dumps(prompt)},
        ],
        "temperature": 0.3,
        "max_tokens": 1000,
    }).encode("utf-8")
    request = urllib.request.Request(
        base_url + "/chat/completions",
        data=payload,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode("utf-8"))
        return _parse_apertus_json(result["choices"][0]["message"]["content"])
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Apertus request failed. Check provider configuration and response.") from exc


def _deterministic_analysis_without_apertus(
    selected_goal: str, rekognition_analysis: dict[str, Any]
) -> dict[str, list[str]]:
    inventory = rekognition_analysis.get("detected_inventory", [])
    object_names = [str(item.get("name", "")).lower() for item in inventory]
    recommendations = [
        f"Prioritize the selected goal: {selected_goal}.",
        "Clear one accessible pathway before buying or replacing furniture.",
    ]
    if "desk" in object_names or "monitor" in object_names:
        recommendations.append("Group workspace items together to keep the work surface usable.")
    if "lamp" not in object_names and "window" not in object_names:
        recommendations.append("Assess task lighting in person; the image cannot confirm illumination levels.")
    return {
        "detected_facts": [f"Detected inventory: {item.get('name', 'unknown')}" for item in inventory[:5]],
        "recommendations": recommendations,
        "limitations": [
            "Apertus was not configured, so these are deterministic rules based on selected goals and detected inventory.",
            "A single image cannot provide exact room dimensions or geometry.",
        ],
    }


def _parse_apertus_json(response_text: str | None) -> dict[str, Any]:
    if not response_text:
        raise HTTPException(status_code=503, detail="Apertus returned an empty response.")

    try:
        clean = response_text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        parsed = json.loads(clean)
        if not isinstance(parsed, dict):
            raise ValueError("Expected a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail="Apertus returned invalid JSON.") from exc

    return {
        "detected_facts": _string_list(parsed.get("detected_facts")),
        "recommendations": _string_list(parsed.get("recommendations")),
        "limitations": _string_list(parsed.get("limitations")),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


# Mount the existing static UI after API routes so /health, /analyze-room, and
# /docs remain handled by FastAPI while / serves the browser application.
FRONTEND_DIRECTORY = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIRECTORY, html=True), name="frontend")
