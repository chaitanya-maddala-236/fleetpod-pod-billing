# Deployment

## Run locally

1. Install Python 3.11 or newer.
2. In a terminal, change to the `FleetPOD` project directory.
3. Create and activate an environment, then install packages:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Copy `.env.example` to `.env`.
5. Set `SESSION_SECRET` to a random string before using the demo outside a local machine. Set `OPENAI_API_KEY` to enable live photo analysis. Leave the key unset to route all photos safely to manual review.
6. Start the server:

   ```powershell
   uvicorn app:app --reload
   ```

7. Visit <http://127.0.0.1:8000>.

The app creates `data/fleetpod.db` and synthetic demo POD images automatically. The data is local to this project folder.

## Demo sign-in

| Role | Email | Password |
| --- | --- | --- |
| Driver | `driver@fleetpod.demo` | `DriverDemo26!` |
| Billing executive | `billing@fleetpod.demo` | `BillingDemo26!` |

These accounts are for this local demo only. Change or disable them before any shared deployment.

## Environment variables

Set names only in repository documentation; never commit `.env` or values.

| Variable | Required | Purpose |
| --- | --- | --- |
| `SESSION_SECRET` | Yes outside local demo | Signs the server-side session cookie. |
| `DATABASE_PATH` | No | SQLite database file path; defaults to `./data/fleetpod.db`. |
| `OPENAI_API_KEY` | Optional | Enables vision analysis of uploaded POD images. |
| `OPENAI_VISION_MODEL` | No | Vision-capable model name; defaults to `gpt-4.1-mini`. |
| `ENVIRONMENT` | No | Set to `production` to mark session cookies `Secure`. |

## Deployment notes

This workspace contains a locally runnable application; no hosted deployment has been created. A production deployment should terminate TLS, set a unique secret, use persistent private storage for SQLite and POD images, back up the database, and restrict access to the billing role. The API key belongs in the host's secret store. The app must be able to make outbound HTTPS requests to the vision API when that integration is enabled.

SMS links and Tally export are intentionally mocked. The upload link expires after 24 hours and is single-use. Tally export downloads a CSV containing each verified trip and its POD image URL; a billing executive marks an invoice after posting it. No invoice is automatically sent.

For a public deployment, use a production database and object store, set explicit retention and deletion rules for PODs, add rate limits and operational monitoring, and complete privacy and access reviews before loading real data.
