# XM Auto Audit — v3.0

Local property matchmaking workspace for Xavier Marks. It imports WhatsApp `cleaned.json` files per agent, parses each message with deterministic Python rules, stores structured records in PostgreSQL schema `xm`, indexes searchable content in Qdrant collection `xm_rag`, and exposes the results to Hermes Agent.

## Local endpoints

- Web UI: `http://127.0.0.1:9004`
- The same local stack is also available at `http://127.0.0.1:9046` (replaces the temporary sample preview).
- Hermes gateway: `http://127.0.0.1:9002`

## Data isolation

- PostgreSQL schema: `xm`
- Qdrant collection: `xm_rag`
- Local runtime data: `data/`
- Every account owns a private workspace. PostgreSQL records and Qdrant payloads use the workspace namespace in `company_id`; the legacy admin archive keeps `xm`, and new users receive a separate `xm-user-<uuid>` namespace. Every import also carries an `agent_name`.

## Matching defaults

- Category and transaction: hard match
- Land area tolerance: 10%
- Building area tolerance: 20%
- Price tolerance: 10%
- Imported location-index alternatives: at most 4 km, WARM pending buyer confirmation; distance never overrides mandatory constraints.

## Matching workspace update

- After login, choose Buyer → Property or Property → Buyer with all dates selected by default; optional Jakarta calendar presets include this month, this week (Monday–Sunday), last month, and a manual range before opening the matching workspace.
- Both search directions use the admin-managed defaults for the selected user (initially `XM Darmo`). Admin can independently enter up to 20 phrases per account separated by newlines or commas; sources matching any phrase are included. User settings are read-only.
- Select one source card to open its recommendations. On mobile, the source list and recommendations appear as separate views, with a back button to return to the list.
- Property contacts support multiple Indonesian phone numbers separated by commas or newlines, normalized to `62`. Matching uses bubble contact details, including alternate numbers, independently of the uploading agent.
- Hot: score ≥80 only after recognised mandatory constraints pass; uncertain evidence or tolerances cap at 79. Warm: 60–79; Belum cocok: no stored match ≥60. Unrequested factors contribute no points. Multiple status filters can be enabled together.
- Exact complete raw texts are grouped before pagination and in both recommendation directions. Original messages remain stored; occurrence badges expose repeats.
- Local accuracy audit and sample limits: [docs/MATCHING_ACCURACY_AUDIT.md](docs/MATCHING_ACCURACY_AUDIT.md).
- Original-data Caesar feedback loop, regression coverage, and measured search/render checks: [docs/CAESAR_QUALITY_AUDIT.md](docs/CAESAR_QUALITY_AUDIT.md). Repeat the local evidence export with `python audit_quality.py --search caesar --output /tmp/caesar-audit.json` inside the API container; the export contains private source messages.
- Settings and location glossary are stored in PostgreSQL. Save & reprocess queues a durable maintenance job; the worker reparses original messages, updates Qdrant, and recomputes matches. Progress survives leaving/reopening the page.
- Advertising phrases with concrete stock details no longer override listing intent. Contact signatures are extracted separately and excluded from structured locations, searchable matching text, and embeddings.
- Hot/Warm scores always include visible text: 🔥 Hot and 🌡️ Warm. Hot cards have a red border and soft pulsing glow, respecting reduced-motion preferences. PDF badges use rounded red/orange backgrounds; WhatsApp links prefill an Indonesian follow-up message.
- Select individual result pairs (or unmatched sources) to download a landscape PDF, with the same website logo, Jakarta generation date, and clickable WhatsApp contacts. Maximum 200 report pairs from 50 sources per export.
- Regression checks: `python3 -m unittest discover -s api -p 'test_*.py'`.
- Existing local services remain at http://127.0.0.1:9004. The Python/PostgreSQL/Qdrant stack is hosted through Docker Compose; the starter `.openai/hosting.json` has no registered cloud Site.

## Login

Default akun admin lokal: `admin@autoaudit.id` / `secret123`. Admin memiliki panel manajemen user (tambah akun, ubah nama/email/password, kunci/buka akun). User hanya dapat membaca pengaturan dan menjalankan pencocokan. Akun terkunci menampilkan layar kosong dengan latar blur dan tautan WhatsApp admin. Atur `XM_ADMIN_EMAIL` dan `XM_ADMIN_PASSWORD` sebelum pertama kali menjalankan instalasi lain. Password disimpan sebagai PBKDF2 hash dan sesi login berlaku tujuh hari.

## Backup lengkap

Gunakan `scripts/backup-data.sh` untuk membuat dump PostgreSQL, snapshot Qdrant `xm_rag`, serta arsip file sumber. Panduan pemulihan tersedia di `docs/BACKUP_RESTORE.md`. Backup data sengaja tidak dilacak Git karena berisi percakapan dan nomor kontak.

## Upgrade v3.0

Release tag: `XM-V3.0`. See [docs/UPGRADE_V3.0.md](docs/UPGRADE_V3.0.md) for updating an existing installation while preserving its data.


## Admin and mobile update

- Migration adds `role` and `is_locked` to existing users without replacing matching data. The configured bootstrap admin is promoted once and receives the configured password (default `secret123`); subsequent restarts preserve the password and active sessions. Other existing accounts become standard users.
- Admin manages the team from **Panel Admin**. Select **Kelola**, edit the user, and save; password changes and email changes revoke that user's sessions. Lock changes take effect on the next API request; the UI checks account state every 5 seconds and on window focus.
- Only admins may change the selected account’s settings, imports, glossary, location index, and recomputation. Locked accounts may only inspect their session and log out. Settings access is enforced on the API, including direct requests.
- The legacy admin workspace preserves its existing search defaults. New accounts start with independent default settings and an empty data workspace. Configure multiple phrases from **Pengaturan → Pencocokan**; the examples are not automatically added to live settings.


## Isolated user workspaces

From **Panel Admin**, choose **Data & setting** on an account. The settings drawer identifies the selected email; matching, JSON imports, glossary CSVs, location data, default searches, tolerances, and weights all belong to that account. **Workspace saya** returns to the admin's own archive. Users can only read and match their own data.

Admin requests carry a selected user ID, checked against the authenticated role on the server. Each request and worker job gets its own workspace context. PostgreSQL queries, uploaded-file directories, Qdrant searches/payloads, result caches, calendar counts, exports, and maintenance jobs are scoped to that workspace. A normal user cannot switch owner by changing a request header or submitting another account's document ID. The selected workspace stays local to the browser view, so admin tabs can manage different users independently.

The existing archive and its settings remain in the admin workspace; nothing is automatically copied to a new user. Upload the appropriate source JSON and location data from that user's **Data & setting** panel. Schema upgrades preserve existing records and add ownership for accounts, glossary entries, and jobs.

`api/test_user_isolation.py` exercises real HTTP requests against a disposable PostgreSQL database: identical uploads in different accounts, settings/glossary/location independence, forbidden owner switches and foreign document IDs, cached and uncached results, exports, worker ownership, reindexing, and concurrent requests. Run the regression suite with `XM_TEST_DATABASE_URL` pointing only to an isolated test database.
