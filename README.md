# Traffic Lab

Agent-based traffic simulation for the IISc QUEST application. The pure-Python engine is in `engine/`, the preset network and scenario are in `schemas/`, the Django REST API is in `backend/`, and the Next.js player is in `frontend/`.

## Local run

1. Python 3.12: `python -m pip install -r requirements.txt`
2. Apply the local SQLite migrations: `python manage.py migrate`
3. Start the API: `python manage.py runserver 127.0.0.1:8000`
4. In `frontend/`, run `pnpm install` and `pnpm dev`.
5. Open `http://localhost:3000`. The API defaults to `http://localhost:8000/api`; set `NEXT_PUBLIC_API_URL` when it differs.

The API uses SQLite locally and PostgreSQL when `DATABASE_URL` is set. Runs exceeding the 10-second engine limit return HTTP 422. The API keeps the 5-run-per-minute anonymous throttle on run creation.

## Checks

- Engine and API: `pytest engine/ backend/`
- Frontend production compile: `cd frontend && pnpm build`

## Hosting configuration

`render.yaml` describes the Django web service. Set `DATABASE_URL` to the Neon connection string, and set `CORS_ALLOWED_ORIGINS` to the deployed Vercel URL. Set `NEXT_PUBLIC_API_URL` in Vercel to the Render API URL plus `/api`. The Vercel project root is `frontend/`.
