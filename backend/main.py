"""Spacewise room analysis API — OpenCV 5 with optional Amazon Bedrock."""

import json
import logging
import os
import re
from typing import Any

import boto3
import cv2
import numpy as np
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from backend.assessment import build_assessment

BACKEND_DIRECTORY = Path(__file__).resolve().parent
BACKEND_ENV_FILE = BACKEND_DIRECTORY / ".env"

try:
    from dotenv import load_dotenv

    # Credentials stay in backend/.env, which is intentionally ignored by Git.
    # Do not override explicitly supplied process settings.
    load_dotenv(dotenv_path=BACKEND_ENV_FILE, override=False)
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("spacewise")

app = FastAPI(title="Spacewise OpenCV Room Analysis", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "SPACEWISE_ALLOWED_ORIGINS",
            "http://localhost:8000,http://127.0.0.1:8000",
        ).split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = int(os.getenv("SPACEWISE_MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
MAX_PIXELS = 24_000_000
BEDROCK_CLIENT_CONFIG = Config(
    connect_timeout=10,
    read_timeout=60,
    # A failed request must not trigger several unexpected inference attempts.
    retries={"max_attempts": 1, "mode": "standard"},
)


def bedrock_is_configured() -> bool:
    """Report readiness without exposing any configuration values."""
    values = [
        os.getenv(name, "").strip()
        for name in (
            "AWS_BEARER_TOKEN_BEDROCK",
            "BEDROCK_MODEL_ID",
            "BEDROCK_REGION",
        )
    ]
    return all(values) and not any(
        value.casefold().startswith(("replace_", "your_", "<"))
        for value in values
    )


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    return max(minimum, min(maximum, value))


def analyze_with_opencv(image_bytes: bytes) -> dict[str, Any]:
    """Measure observable image properties, not semantic object identities."""
    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)

    if image is None:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a readable JPEG or PNG image.",
        )

    height, width = image.shape[:2]

    if width * height > MAX_PIXELS:
        raise HTTPException(
            status_code=400,
            detail="Image resolution is too large. Use a photo under 24 megapixels.",
        )

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    brightness = float(np.mean(gray))
    contrast = float(np.std(gray))
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    edges = cv2.Canny(gray, 75, 150)
    edge_density = float(np.count_nonzero(edges) / edges.size * 100)

    contours, _ = cv2.findContours(
        edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    meaningful_contours = sum(
        1 for contour in contours
        if cv2.contourArea(contour) >= (width * height * 0.0005)
    )

    saturation = float(np.mean(hsv[:, :, 1]))

    # These are image-quality heuristics, not calibrated probabilities.
    sharpness_score = round(clamp(laplacian_variance / 5))
    contrast_score = round(clamp(contrast * 2))

    if brightness < 65:
        lighting = "Low light"
    elif brightness > 205:
        lighting = "Very bright"
    else:
        lighting = "Moderate lighting"

    return {
        "width": width,
        "height": height,
        "brightness": round(brightness, 2),
        "contrast": round(contrast, 2),
        "laplacian_variance": round(laplacian_variance, 2),
        "edge_density_percent": round(edge_density, 2),
        "meaningful_contours": meaningful_contours,
        "mean_saturation": round(saturation, 2),
        "lighting_classification": lighting,
        "quality": {
            "sharpness": sharpness_score,
            "contrast": contrast_score,
        },
    }


def local_recommendations(goal: str, properties: dict) -> list[str]:
    """Transparent rule-based fallback when Bedrock is not configured."""
    recommendations = []
    normalized = goal.lower()

    if properties["brightness"] < 90:
        recommendations.append(
            "Improve illumination with layered lighting and keep windows unobstructed."
        )
    elif properties["brightness"] > 205:
        recommendations.append(
            "Consider curtains or blinds to control glare in very bright areas."
        )

    if properties["laplacian_variance"] < 80:
        recommendations.append(
            "Retake the photograph with steadier focus for more reliable visual analysis."
        )

    if any(word in normalized for word in ("space", "storage", "clutter", "small")):
        recommendations.append(
            "Prioritize vertical storage and keep primary walking routes clear."
        )

    if any(word in normalized for word in ("budget", "cost", "affordable")):
        recommendations.append(
            "Rearrange existing furniture before purchasing new items."
        )

    if any(word in normalized for word in ("design", "style", "decor")):
        recommendations.append(
            "Choose a consistent color palette and avoid unnecessary visual clutter."
        )

    if not recommendations:
        recommendations.append(
            "Evaluate furniture placement, lighting, and circulation before making changes."
        )

    return recommendations


def combine_recommendations(
    local: list[str], semantic: list[str], maximum: int = 12
) -> list[str]:
    """Retain OpenCV-derived advice while adding distinct model suggestions."""
    combined = []
    seen = set()
    for recommendation in [*local, *semantic]:
        normalized = recommendation.casefold().strip()
        if normalized and normalized not in seen:
            combined.append(recommendation)
            seen.add(normalized)
        if len(combined) >= maximum:
            break
    return combined


def parse_bedrock_json(text: str) -> dict:
    """Accept a JSON object, including one enclosed in a Markdown code fence."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("Bedrock returned non-JSON output")
        return {}


def analyze_with_bedrock(
    image_bytes: bytes,
    image_format: str,
    goal: str,
    properties: dict,
) -> dict:
    """Optional multimodal interpretation using a configured Bedrock model."""
    model_id = os.getenv("BEDROCK_MODEL_ID", "").strip()

    if not model_id:
        return {}

    region = os.getenv(
        "BEDROCK_REGION",
        os.getenv("AWS_REGION", "ap-south-1"),
    )

    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=BEDROCK_CLIENT_CONFIG,
    )

    prompt = (
        "You are a cautious interior-space analysis assistant. "
        "Examine the attached room photograph and the measured OpenCV features. "
        "Identify only clearly visible furniture or room objects. "
        "Do not invent measurements, prices, hidden objects, or architectural details. "
        "Return ONLY a JSON object with these keys: "
        "'detected_inventory' (array of objects with 'name' and 'instances'), "
        "'recommendations' (array of short actionable strings), "
        "'limitations' (array of strings), "
        "'detected_facts' (array of strings). "
        "Do not output confidence percentages because they are not calibrated. "
        f"Improvement goal: {goal}. "
        f"OpenCV measurements: {json.dumps(properties)}"
    )

    response = client.converse(
        modelId=model_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {"text": prompt},
                    {
                        "image": {
                            "format": image_format,
                            "source": {"bytes": image_bytes},
                        }
                    },
                ],
            }
        ],
        inferenceConfig={"maxTokens": 1100, "temperature": 0.2},
    )

    content = response.get("output", {}).get("message", {}).get("content", [])
    text = "\n".join(
        block["text"] for block in content
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )

    return parse_bedrock_json(text)


def normalize_inventory(values: Any) -> list[dict]:
    """Keep frontend compatibility without fabricating model confidence."""
    if not isinstance(values, list):
        return []

    inventory = []

    for value in values[:25]:
        if not isinstance(value, dict):
            continue

        name = value.get("name")
        if not isinstance(name, str) or not name.strip():
            continue

        instances = value.get("instances")
        if not isinstance(instances, int) or isinstance(instances, bool):
            instances = None

        inventory.append(
            {
                "name": name.strip()[:80],
                "confidence": None,
                "instances": instances if instances and instances > 0 else None,
            }
        )

    return inventory


def string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item.strip()
        for item in value[:20]
        if isinstance(item, str) and item.strip()
    ]


@app.get("/health")
def health():
    return {
        "status": "ok",
        "opencv_version": cv2.__version__,
        "bedrock_configured": bedrock_is_configured(),
    }


@app.post("/analyze-room")
async def analyze_room(
    goal: str = Form(...),
    photo: UploadFile = File(...),
):
    if photo.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(
            status_code=400,
            detail="Only JPEG and PNG photographs are supported.",
        )

    image_bytes = await photo.read(MAX_UPLOAD_BYTES + 1)
    await photo.close()

    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="The photograph must be smaller than 10 MB.",
        )

    if not image_bytes:
        raise HTTPException(status_code=400, detail="The uploaded image is empty.")

    if len(goal.strip()) > 500:
        raise HTTPException(status_code=400, detail="Goal description is too long.")

    properties = analyze_with_opencv(image_bytes)

    # Determine actual encoded format, not just the browser's MIME label.
    if image_bytes.startswith(b"\xff\xd8\xff"):
        image_format = "jpeg"
    elif image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        image_format = "png"
    else:
        raise HTTPException(
            status_code=400,
            detail="The file must contain valid JPEG or PNG image data.",
        )

    limitations = [
        "OpenCV image measurements do not establish real-world room dimensions.",
        "A single photograph cannot reliably establish hidden objects or total floor area.",
    ]

    detected_inventory = []
    detected_facts = [
        f"Image resolution: {properties['width']} × {properties['height']} pixels.",
        f"Lighting classification: {properties['lighting_classification']}.",
        f"Detected external contours above the area threshold: {properties['meaningful_contours']}.",
    ]

    recommendations = local_recommendations(goal, properties)
    analysis_method = "opencv-local"

    if bedrock_is_configured():
        try:
            bedrock = analyze_with_bedrock(
                image_bytes, image_format, goal, properties
            )

            if bedrock:
                detected_inventory = normalize_inventory(
                    bedrock.get("detected_inventory")
                )
                recommendations = combine_recommendations(
                    recommendations,
                    string_list(bedrock.get("recommendations")),
                )
                limitations.extend(string_list(bedrock.get("limitations")))
                detected_facts.extend(string_list(bedrock.get("detected_facts")))
                analysis_method = "opencv-bedrock"

        except (BotoCoreError, ClientError, NoCredentialsError) as exc:
            logger.warning("Bedrock unavailable: %s", type(exc).__name__)
            limitations.append(
                "Amazon Bedrock was unavailable; local OpenCV analysis was used."
            )
        except Exception:
            logger.exception("Unexpected Bedrock analysis failure")
            limitations.append(
                "AI interpretation failed; local OpenCV analysis was used."
            )

    vision_analysis = {
        "detected_inventory": detected_inventory,
        "image_properties": properties,
    }

    assessment = build_assessment(goal, vision_analysis, recommendations)

    return {
        "selected_goal": goal,
        "storage": {"bucket": None, "key": None},
        "detected_inventory": detected_inventory,
        "image_properties": properties,
        "detected_facts": detected_facts,
        "recommendations": recommendations,
        "limitations": limitations,
        "analysis_method": analysis_method,
        "assessment": assessment,
    }


# Mount frontend last so API routes remain accessible.
frontend_directory = BACKEND_DIRECTORY.parent / "frontend"

if frontend_directory.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(frontend_directory), html=True),
        name="frontend",
    )
