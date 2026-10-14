import json
import os
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types


load_dotenv()

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

    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        raise HTTPException(
            status_code=503,
            detail="Missing GEMINI_API_KEY. Configure the backend environment before analysis.",
        )

    image_bytes = await photo.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")

    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Please upload an image under 10 MB.")

    s3_key = _build_s3_key(photo.filename)
    s3_client = _aws_client("s3")
    rekognition_client = _aws_client("rekognition")

    _verify_bucket_exists(s3_client, bucket_name)
    _upload_to_s3(s3_client, bucket_name, s3_key, image_bytes, photo.content_type)
    rekognition_analysis = _analyze_with_rekognition(
        rekognition_client,
        bucket_name,
        s3_key,
    )
    gemini_analysis = _analyze_with_gemini(
        api_key=gemini_api_key,
        selected_goal=goal,
        rekognition_analysis=rekognition_analysis,
    )

    return {
        "selected_goal": goal,
        "storage": {
            "bucket": bucket_name,
            "key": s3_key,
        },
        "detected_inventory": rekognition_analysis["detected_inventory"],
        "image_properties": rekognition_analysis["image_properties"],
        "recommendations": gemini_analysis.get("recommendations", []),
        "limitations": gemini_analysis.get("limitations", []),
        "detected_facts": gemini_analysis.get("detected_facts", []),
    }


def _aws_client(service_name: str):
    region_name = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
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
            response = rekognition_client.detect_labels(
                Image=image,
                MaxLabels=75,
                MinConfidence=55,
            )
        else:
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


def _analyze_with_gemini(
    api_key: str,
    selected_goal: str,
    rekognition_analysis: dict[str, Any],
) -> dict[str, Any]:
    client = genai.Client(api_key=api_key)
    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    prompt = {
        "role": "Spacewise room improvement analyst",
        "selected_goal": selected_goal,
        "rekognition_analysis": rekognition_analysis,
        "instructions": [
            "Recommend practical improvements for an already-lived-in room.",
            "Respect existing furniture unless the user explicitly asks to replace something.",
            "Do not fabricate objects that are not in the Rekognition data.",
            "Do not claim exact room dimensions, measurements, or precise geometry from one photo.",
            "Clearly separate detected facts from recommendations and limitations.",
            "Return only JSON with keys: detected_facts, recommendations, limitations.",
        ],
    }

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=json.dumps(prompt),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Gemini analysis failed.") from exc

    return _parse_gemini_json(response.text)


def _parse_gemini_json(response_text: str | None) -> dict[str, Any]:
    if not response_text:
        raise HTTPException(status_code=503, detail="Gemini returned an empty response.")

    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail="Gemini returned invalid JSON.") from exc

    return {
        "detected_facts": _string_list(parsed.get("detected_facts")),
        "recommendations": _string_list(parsed.get("recommendations")),
        "limitations": _string_list(parsed.get("limitations")),
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]
