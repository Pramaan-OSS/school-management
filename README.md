[![CI](https://github.com/Pramaan-OSS/school-management/actions/workflows/ci.yml/badge.svg)](https://github.com/Pramaan-OSS/school-management/actions/workflows/ci.yml)

# School Management

A complete school administration product: admissions, students, attendance,
subjects and schedules, assessments and grade books, fees, hostel and rooms,
built on one locally runnable stack.

## Quick start

1. Install [Docker](https://docs.docker.com/get-docker/) with Compose.
2. From a fresh clone:

   ```sh
   cp .env.example .env    # then paste PRAMAAN_API_KEY=... into .env
   ./start
   ```

3. Open the printed address (default `http://localhost:3037`) and sign in as
   `Administrator`. The generated password is in `.runtime/local-admin-password`.

Without a key the product still runs: sign-in, students, attendance, schedules
and records all work; fee payments and email delivery show a plain note until
`PRAMAAN_API_KEY` is set in `.env`.

Everything else is generated on first run (database password, encryption key,
Administrator password, local site name) and kept private in `.env` and
`.runtime/`. To stop: `docker compose --env-file .env -f docker/docker-compose.yml down`.
Back up `.env` together with the private volumes.

Use `./start --production` for the production server, or `./start --development`
for local development. The selection is saved for later starts. Both modes serve
pages and realtime updates through the printed address; static scripts and styles
are compressed for faster first loads.

## Fee payments

Fee payments need the school's own payment account: open Education Settings in
the desk and use **Connect Payment Account**, then **Check Payment Account**.
Paying people always finish the payment themselves on the hosted payment page.
Payment onboarding requires a public return address; the local-only Docker address
cannot complete that connection. Availability and account consent are checked separately.

## Optional setup

- `PRAMAAN_BASE_URL` in `.env` (empty uses the default service address).
- `PRAMAAN_TAX_CATEGORY` in `.env`: school-fee payment links default to `edtech`.
  The single client sends this category on both estimates and link creation; no account header is needed.
- School name, abbreviation and logo: Education Settings.
- Outgoing school email: **Email Sender** in Education Settings (one name-and-address setting).
  Its default is `School Management <noreply@updates.pramaan.one>`.
  Local compatibility mailbox records do not override this sender.

## Built on

This product is built on the [Frappe Education](https://github.com/frappe/education)
open-source project (GNU GPL v3), rewired so that every outside service call
goes through one Pramaan API. The original licence text is preserved in
`LICENSE-ORIGINAL`.
