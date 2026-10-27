# Spacewise

Spacewise is a hackathon MVP for improving an existing lived-in room. Instead
of designing an empty house or a blank interior, it starts from a real room
photo and focuses on practical upgrades such as better floor space, lighting,
workspace quality, appearance, and overall livability.

## Current MVP Architecture

This MVP is intentionally small:

- `backend/` contains a Python FastAPI application with a `GET /health`
  endpoint and a `POST /analyze-room` endpoint.
- `frontend/` contains a static single-page interface for uploading a room
  photo, selecting improvement goals, and showing structured analysis results.
- `.env.example` documents AWS and Gemini environment variables without
  including real credentials.

No database, authentication, Docker, infrastructure automation, image
generation, custom ML training, or agent framework is included.

The analysis flow is:

1. The frontend sends the selected room photo and improvement goal to FastAPI.
2. FastAPI uploads the image to an existing S3 bucket.
3. Amazon Rekognition detects approximate room inventory and image properties.
4. When `BEDROCK_MODEL_ID` is configured and enabled in the bucket's region,
   Amazon Bedrock receives the photo plus structured Rekognition output and
   returns contextual recommendations. Without it, the MVP uses its existing
   deterministic, inventory-based recommendation fallback.

Rekognition detections are approximate. Spacewise does not infer exact room
dimensions or precise geometry from one photograph.

## Assessment meters

Each completed analysis returns five animated percentage meters: Design
Confidence, Space Utilization, Budget Compatibility, Feasibility Confidence,
and Overall Compatibility. Scores are deterministic: detected inventory,
Rekognition confidence and image quality, selected goal count, and the number
of deterministic/Gemini recommendations are the only inputs. Missing inventory
uses fixed 35%/50%/60% baselines for design/utilization/budget; missing
confidence uses a 55% feasibility baseline; missing image quality adds no
quality adjustment. Overall Compatibility is a 30/25/20/25 weighted average.
The API also returns these fallback rules with every assessment.

## Local Setup

From the project root:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Configure local environment variables before using analysis:

```bash
copy .env.example .env
```

Set these values in your terminal session (PowerShell example):

```text
$env:AWS_REGION="us-east-1"
$env:SPACEWISE_S3_BUCKET="your_existing_spacewise_bucket_name"
# Optional: enables live multimodal Bedrock recommendations. Choose a model
# enabled for this AWS region and supported by the Bedrock Converse API.
$env:BEDROCK_MODEL_ID="your_enabled_multimodal_bedrock_model_id"
```

AWS credentials should come from your local AWS CLI profile or environment. The
application does not create buckets or infrastructure automatically.

Run the API:

```bash
python -m uvicorn backend.main:app --reload
```

The API health check will be available at:

```text
http://localhost:8000/health
```

The room analysis endpoint is:

```text
POST http://localhost:8000/analyze-room
```

## Vercel deployment

The repository root contains `app.py`, which exports the existing FastAPI
application for Vercel. It serves `GET /health`, `POST /analyze-room`, and the
existing frontend through the FastAPI static-files mount. Bedrock is optional:
when no Bedrock environment variables are configured, the OpenCV-only fallback
and all five deterministic assessment meters continue to work.

`vercel.json` limits hosted uploads to 4 MB because Vercel Functions limit a
request body to 4.5 MB. Local FastAPI retains the 10 MB default. The deployment
uses the OpenCV 5 headless wheel because the application does not use GUI APIs.

Before deploying, install the Vercel CLI, authenticate, and run a local Vercel
build from the repository root:

```powershell
npm install --global vercel
vercel login
vercel build
vercel dev
```

After checking `/health` and an OpenCV-only room upload locally, create the
deployment deliberately with:

```powershell
vercel
# Use this only when you intend to release to production:
vercel --prod
```

Do not add `AWS_BEARER_TOKEN_BEDROCK` to the project files or Vercel unless AI
interpretation is intentionally enabled later. If it is enabled, add it only
in Vercel Project Settings → Environment Variables, together with
`BEDROCK_MODEL_ID` and `BEDROCK_REGION`.

It accepts multipart form fields:

- `photo`: image file
- `goal`: selected improvement goal text

Open `http://127.0.0.1:8000`. FastAPI serves the frontend itself, so the photo
form and API always use the same origin.

## Environment Variables

Credentials and API keys must be terminal environment variables available only to
the backend process; they must never be committed, hardcoded, or exposed to
frontend JavaScript. Bedrock is optional: without `BEDROCK_MODEL_ID`, the API
returns deterministic inventory-and-goal-based recommendations and assessments.
