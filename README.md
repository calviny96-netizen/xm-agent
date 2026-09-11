# XM Auto Audit — v1.2

Local property matchmaking workspace for Xavier Marks. It imports WhatsApp `cleaned.json` files per agent, parses each message with deterministic Python rules, stores structured records in PostgreSQL schema `xm`, indexes searchable content in Qdrant collection `xm_rag`, and exposes the results to Hermes Agent.

## Local endpoints

- Web UI: `http://127.0.0.1:9004`
- The same local stack is also available at `http://127.0.0.1:9046` (replaces the temporary sample preview).
- Hermes gateway: `http://127.0.0.1:9002`

## Data isolation

- PostgreSQL schema: `xm`
- Qdrant collection: `xm_rag`
- Local runtime data: `data/`
- Every import and parsed record carries `company_id=xm` and an `agent_name`.

## Matching defaults

- Category and transaction: hard match
- Land area tolerance: 10%
- Building area tolerance: 20%
- Price tolerance: 10%
- Imported location-index alternatives: at most 4 km, WARM pending buyer confirmation; distance never overrides mandatory constraints.

## Matching workspace update

- Switch Buyer → Property or Property → Buyer; source date/search/status filters are applied before pagination.
- Property contacts support multiple Indonesian phone numbers separated by commas or newlines, normalized to `62`. Matching uses bubble contact details, including alternate numbers, independently of the uploading agent.
- Hot: score ≥80 only after recognised mandatory constraints pass; uncertain evidence or tolerances cap at 79. Warm: 60–79; Belum cocok: no stored match ≥60. Unrequested factors contribute no points. Multiple status filters can be enabled together.
- Exact complete raw texts are grouped before pagination and in both recommendation directions. Original messages remain stored; occurrence badges expose repeats.
- Local accuracy audit and sample limits: [docs/MATCHING_ACCURACY_AUDIT.md](docs/MATCHING_ACCURACY_AUDIT.md).
- Original-data Caesar feedback loop, regression coverage, and measured search/render checks: [docs/CAESAR_QUALITY_AUDIT.md](docs/CAESAR_QUALITY_AUDIT.md). Repeat the local evidence export with `python audit_quality.py --search caesar --output /tmp/caesar-audit.json` inside the API container; the export contains private source messages.
- Settings and location glossary are stored in PostgreSQL. Save & reprocess queues a durable maintenance job; the worker reparses original messages, updates Qdrant, and recomputes matches. Progress survives leaving/reopening the page.
- Advertising phrases with concrete stock details no longer override listing intent. Contact signatures are extracted separately and excluded from structured locations, searchable matching text, and embeddings.
- Select individual result pairs (or unmatched sources) to download a landscape PDF, with the same website logo, Jakarta generation date, and clickable WhatsApp contacts. Maximum 200 report pairs from 50 sources per export.
- Regression checks: `python3 -m unittest discover -s api -p 'test_*.py'`.
- Existing local services remain at http://127.0.0.1:9004. The Python/PostgreSQL/Qdrant stack is hosted through Docker Compose; the starter `.openai/hosting.json` has no registered cloud Site.

## Login

Default akun lokal: `admin@autoaudit.id` / `admin`. Atur `XM_ADMIN_EMAIL` dan `XM_ADMIN_PASSWORD` sebelum pertama kali menjalankan instalasi lain. Password disimpan sebagai PBKDF2 hash dan sesi login berlaku tujuh hari.

## Backup lengkap

Gunakan `scripts/backup-data.sh` untuk membuat dump PostgreSQL, snapshot Qdrant `xm_rag`, serta arsip file sumber. Panduan pemulihan tersedia di `docs/BACKUP_RESTORE.md`. Backup data sengaja tidak dilacak Git karena berisi percakapan dan nomor kontak.

## Upgrade v1.2

Release tag: `XM-V1.2`. See [docs/UPGRADE_V1.2.md](docs/UPGRADE_V1.2.md) for updating an existing installation without replacing its database.
