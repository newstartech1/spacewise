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
4. Gemini receives the structured Rekognition output and selected goal, then
   returns practical recommendations for an already-lived-in room.

Rekognition detections are approximate. Spacewise does not infer exact room
dimensions or precise geometry from one photograph.

## Local Setup

From the project root:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Configure local environment variables before using analysis:

```bash
copy .env.example .env
```

Set these values in your shell or load them from `.env` with your preferred
local workflow:

```text
AWS_REGION=us-east-1
SPACEWISE_S3_BUCKET=your_existing_spacewise_bucket_name
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-1.5-flash
```

AWS credentials should come from your local AWS CLI profile or environment. The
application does not create buckets or infrastructure automatically.

Run the API:

```bash
uvicorn main:app --reload
```

The API health check will be available at:

```text
http://localhost:8000/health
```

The room analysis endpoint is:

```text
POST http://localhost:8000/analyze-room
```

It accepts multipart form fields:

- `photo`: image file
- `goal`: selected improvement goal text

Open the frontend by serving the `frontend/` directory with any simple static
server. For example:

```bash
cd frontend
python -m http.server 5500
```

Then open:

```text
http://localhost:5500
```

## Environment Variables

Create a local `.env` from `.env.example` when future integrations are added:

```bash
copy .env.example .env
```

Do not commit `.env`. API keys and AWS credentials must stay on the backend and
must never be exposed to frontend JavaScript.
