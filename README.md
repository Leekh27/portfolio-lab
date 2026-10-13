# Portfolio Lab — Free Cloud Edition

Architecture: Render free FastAPI server + Neon free PostgreSQL. The server filesystem is ephemeral; portfolio data is stored in Neon, not SQLite.

## Setup
1. Create a private GitHub repository and upload these project files (do not upload `.env`).
2. At https://console.neon.tech create a Free project, copy its **pooled** PostgreSQL connection string with SSL enabled.
3. At https://dashboard.render.com choose New > Blueprint and select the repository containing `render.yaml`.
4. Select Free plan and enter secret environment variables: `DATABASE_URL` (Neon connection string), `APP_USERNAME`, `APP_PASSWORD`. `OPENAI_API_KEY` is optional; leave empty if not using AI.
5. Deploy. Wait for the `onrender.com` HTTPS URL. Open on PC or mobile, sign in with HTTP Basic Auth credentials.
6. After adding holdings, download a manual JSON backup by visiting `/api/backup` and store it offline securely. Repeat after important changes.

## Limitations and safety
- Free Render service sleeps after 15 minutes of inactivity; first request may take about a minute.
- Neon Free has usage/storage limits. Neither free hosting nor this app guarantees zero data loss. Keep offline backups.
- Basic Auth over HTTPS is intended for **single-user personal use**, not a multi-user product. Use a strong unique password. Never put secrets in GitHub or browser-side JS.
- `/api/backup` is protected by the same login. Restore is manual; save the exported JSON separately.
- Market data is from unofficial Yahoo Finance and may be delayed/unavailable; AI API incurs separate usage costs.
- The code has not been deployed or verified against live accounts; test before storing important records.
