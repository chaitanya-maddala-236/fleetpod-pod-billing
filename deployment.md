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

The app creates `data/fleetpod.db` and synthetic demo POD images automatically. `DATA_DIR` controls where both the database (by default) and POD images are stored; `DATABASE_PATH` can override the database file independently.

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
| `DATA_DIR` | No | Directory for POD images and the default SQLite database; defaults to `./data`. |
| `DATABASE_PATH` | No | SQLite database file path; defaults to `<DATA_DIR>/fleetpod.db`. |
| `DATABASE_URL` | Required on Render | PostgreSQL connection string; set to the Neon project URL. When blank, the app uses local SQLite. |
| `OPENAI_API_KEY` | Optional | Enables vision analysis of uploaded POD images. |
| `OPENAI_VISION_MODEL` | No | Vision-capable model name; defaults to `gpt-4.1-mini`. |
| `ENVIRONMENT` | No | Set to `production` to mark session cookies `Secure`. |

## Deploy free on Render with Neon

1. Create a free PostgreSQL project on Neon and copy its pooled connection string into Render as `DATABASE_URL` (keep the password private).
2. Push this repository to a GitHub account you control.
3. In Render, choose **New → Blueprint**, connect the repository, and select its `render.yaml`. The Blueprint uses Render's free web service plan.
4. After the first deploy is live, open the generated `onrender.com` URL and sign in with one of the demo accounts above. For a shared demo, replace or disable these seeded accounts before sharing the URL.
5. To enable live photo analysis, add `OPENAI_API_KEY` as a secret environment variable in Render. Without it, uploads route to manual review.

`render.yaml` sets `DATA_DIR=/tmp/fleetpod`, reads `DATABASE_URL` for Neon, enables secure session cookies, generates `SESSION_SECRET`, and configures `/api/health` as the health check. SQLite remains the local development default. In the hosted setup, trip records and compressed POD images (maximum 300 KB) are stored in PostgreSQL so they survive Render restarts. This keeps the demo fully on free tiers, but it is a low-volume prototype and should move POD binaries to object storage before production.

Render's free web service sleeps after 15 minutes without traffic, and the first request after sleep can take about a minute. It also has an ephemeral filesystem, so do not store hosted user data there. Free Render Postgres expires after 30 days; this setup uses Neon instead for database persistence. Free tiers can change; confirm current limits in each provider dashboard before relying on them.

The public source repository is <https://github.com/chaitanya-maddala-236/fleetpod-pod-billing>. A Neon project and live Render service have not been created yet. `DATABASE_URL` and any vision API key belong in the host's secret store. The app must be able to make outbound HTTPS requests to the vision API when that integration is enabled.

SMS links and Tally export are intentionally mocked. The upload link expires after 24 hours and is single-use. Tally export downloads a CSV containing each verified trip and its POD image URL; a billing executive marks an invoice after posting it. No invoice is automatically sent.

For a production deployment, use managed PostgreSQL and object storage, set explicit retention and deletion rules for PODs, add rate limits and operational monitoring, and complete privacy and access reviews before loading real data.
