# FleetPOD

FleetPOD is a small proof-of-delivery and billing workflow for Company A's road transport team. It covers driver capture, AI-assisted photo checks, human review, billing export, and a missing-POD dashboard.

## Run locally

1. Use Python 3.13 or newer.
2. Open a terminal in this directory.
3. Create a virtual environment and install dependencies:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env`. Set `SESSION_SECRET` to a random value. Add `OPENAI_API_KEY` to enable real POD photo analysis; without it, uploads go to the human review queue.
5. Start the app:

   ```powershell
   uvicorn app:app --reload
   ```

6. Open <http://127.0.0.1:8000>.

Demo accounts are documented in [deployment.md](deployment.md). Locally, SQLite and generated demo POD images are created under `data/` on first run. Set `DATABASE_URL` to use PostgreSQL; the Render Blueprint stores hosted POD images in PostgreSQL so they persist on the free web service.

## Demo flow

- Sign in as the driver and capture a photo for TRP-66134, which starts in retake status.
- The app compresses the image below 300 KB and stores it for later sync if the network is unavailable.
- With a vision API key, the configured model checks the LR, consignee stamp, quantity, remarks, date, and signature. Shortage or damage remarks and uncertain readings go to a billing executive.
- Sign in as billing to correct a review item, export verified PODs to CSV, mark an invoice after posting it, or copy a read-only trip link.

## Technical detail

See [Technical Design Document.pdf](Technical%20Design%20Document.pdf) and [deployment.md](deployment.md). The app uses FastAPI, SQLite, secure signed session cookies, a static responsive frontend, IndexedDB for offline photo submissions, and the OpenAI Responses API for optional vision checks.

## Live demo and deployment

Live app: <https://fleetpod.onrender.com>. The free Render web service uses Neon PostgreSQL to retain trips and uploaded POD images across Render restarts; local development defaults to SQLite. The repository includes a Render Blueprint in [render.yaml](render.yaml). See [deployment.md](deployment.md) for demo credentials and setup steps.

## Test

```powershell
pytest -q
```

## Current limits

- Public source: <https://github.com/chaitanya-maddala-236/fleetpod-pod-billing>.
- The public demo has no paid vision API credential configured. Its upload flow safely routes to human review; set `OPENAI_API_KEY` in a private deployment to enable vision extraction.
- SMS and Tally are mocked: the app creates copyable one-time upload links and a CSV export, but sends no messages and makes no external accounting-system calls.
- AI errors or missing credentials never produce a verified result. A billing executive must review the image and correct extracted values.
- The generated POD images and trip records are synthetic examples. Do not add real consignee personal data to this demo.
