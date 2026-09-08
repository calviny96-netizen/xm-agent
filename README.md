# XM Auto Audit

Local property matchmaking workspace for Xavier Marks. It imports WhatsApp `cleaned.json` files per agent, parses each message with deterministic Python rules, stores structured records in PostgreSQL schema `xm`, indexes searchable content in Qdrant collection `xm_rag`, and exposes the results to Hermes Agent.

## Local endpoints

- Web UI: `http://127.0.0.1:9004`
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
- Location radius policy: 3 km primary, 5 km extended

## Matching workspace update

- Switch Buyer → Property or Property → Buyer; source date/search/status filters are applied before pagination.
- Property contacts support multiple Indonesian phone numbers separated by commas or newlines, normalized to `62`. Matching uses bubble contact details, including alternate numbers, independently of the uploading agent.
- Hot: score ≥80; Warm: 60–79; Belum cocok: no stored match ≥60. Multiple status filters can be enabled together.
- Settings and location glossary are stored in PostgreSQL. Save & reprocess queues a durable maintenance job; the worker reparses original messages, updates Qdrant, and recomputes matches. Progress survives leaving/reopening the page.
- Advertising phrases with concrete stock details no longer override listing intent. Contact signatures are extracted separately and excluded from structured locations, searchable matching text, and embeddings.
- Select individual result pairs (or unmatched sources) to download a landscape PDF, with the same website logo, Jakarta generation date, and clickable WhatsApp contacts. Maximum 200 report pairs from 50 sources per export.
- Regression checks: `python3 -m unittest discover -s api -p 'test_*.py'`.
- Existing local services remain at http://127.0.0.1:9004. The Python/PostgreSQL/Qdrant stack is hosted through Docker Compose; the starter `.openai/hosting.json` has no registered cloud Site.
