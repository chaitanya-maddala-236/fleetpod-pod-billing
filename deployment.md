# FleetPOD deployment

## Live demo

- App: https://fleetpod.onrender.com
- Source: https://github.com/chaitanya-maddala-236/fleetpod-pod-billing
- Hosting: Render Free web service + Neon Free PostgreSQL (Singapore region).

The public demo is seeded with synthetic trips and the demo accounts below. Render Free sleeps after inactivity, so the first visit may take about a minute to wake. POD photos and trip data are stored in Neon; the Render filesystem is temporary.

## Reviewer sign-in

| Role | Email | Password |
| --- | --- | --- |
| Driver | `driver@fleetpod.demo` | `DriverDemo26!` |
| Billing executive | `billing@fleetpod.demo` | `BillingDemo26!` |

The demo has no paid vision API credential configured. POD uploads therefore go to the billing review queue instead of being auto-verified. Set `OPENAI_API_KEY` in a private environment to enable live vision extraction; an API error still routes the POD to human review.

## Run locally

1. Install Python 3.13 or newer.
2. Open a terminal in the project directory and create a virtual environment:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env`. Set `SESSION_SECRET` to a random value. `OPENAI_API_KEY` is optional; without it, uploads safely enter manual review.
4. Start the app:

   ```powershell
   uvicorn app:app --reload
   ```

5. Visit <http://127.0.0.1:8000> and use either demo account above.

The app creates `data/fleetpod.db` and synthetic demo POD images on first run. `DATA_DIR` sets the data directory; `DATABASE_PATH` can override the SQLite file. Local SQLite is used when `DATABASE_URL` is unset.

## Deploy or reproduce the free deployment

1. Create a free Neon PostgreSQL project and copy its pooled connection string into the host's secret store as `DATABASE_URL`.
2. Push this repository to GitHub.
3. In Render, select **New > Blueprint**, connect the repository, and apply `render.yaml`. It defines the free Python web service, health check, and non-secret settings.
4. Add the Neon connection string as the secret `DATABASE_URL`. Render generates `SESSION_SECRET` from the Blueprint. Do not commit secret values.
5. Wait for `/api/health` to pass, open the generated `onrender.com` URL, and sign in with a demo account.
6. To enable real photo extraction, add `OPENAI_API_KEY` as a secret and keep it out of GitHub and the submission files.

## Environment variables

| Name | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Hosted | Neon PostgreSQL connection string. Blank locally selects SQLite. |
| `SESSION_SECRET` | Yes for shared deployment | Signs the session cookie. |
| `ENVIRONMENT` | Hosted | Set to `production` to mark session cookies Secure. |
| `DATA_DIR` | No | Local files directory; Render sets `/tmp/fleetpod`. Hosted POD bytes are kept in PostgreSQL. |
| `DATABASE_PATH` | No | SQLite database path for local development. |
| `OPENAI_API_KEY` | Optional | Enables vision analysis. Missing or failing API routes uploads to human review. |
| `OPENAI_VISION_MODEL` | Optional | Vision-capable model name; defaults to `gpt-4.1-mini`. |

## Prototype limits

- Render Free is ephemeral and may sleep; Neon Free is the persistent database for this demo. Free-tier limits can change.
- POD image bytes are stored in PostgreSQL to avoid losing them when Render restarts. A production system should use managed object storage, retention rules, and deletion jobs.
- SMS and Tally are mocked. The app creates a copyable single-use upload link and exports a CSV with POD image links; it sends no messages and no invoice is sent automatically.
- Demo accounts and all sample trip/consignee data are synthetic. Do not use this public demo for real personal or business records.

## Verification

Run the automated checks from the project directory:

```powershell
pytest -q
```

The current suite passes 8 tests covering sign-in and role access, photo upload and fallback, review/retake decisions, billing export, one-time upload links, and invoice state.
