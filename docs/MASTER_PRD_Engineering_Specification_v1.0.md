# MOTIONFORGE AI

## Master Product Requirements Document (PRD) & Master Engineering Execution Specification

**Dokumen:** MF-MASTER-SPEC-001\
**Versi:** 1.0\
**Tanggal:** 26 November 2026\
**Status:** Baseline untuk product discovery, engineering
implementation, dan production readiness\
**Nama produk:** MotionForge AI (nama kerja; dapat diganti tanpa
mengubah arsitektur)\
**Kategori:** AI-powered Motion Graphic & Video Production Studio\
**Bahasa dokumen:** Bahasa Indonesia\
**Core video engine:** Remotion\
**Prinsip:** End-to-end production, structured output, deterministic
rendering, secure-by-default, versioned artifacts.

------------------------------------------------------------------------

# 0. Cara Menggunakan Dokumen

Dokumen ini adalah baseline produk dan engineering untuk membangun
platform yang mengubah brief/prompt menjadi video motion graphic utuh.
Dokumen ini bukan klaim bahwa sistem telah diimplementasikan. Semua
fitur, endpoint, tabel, dan workflow di bawah adalah spesifikasi target.

## 0.1 Konvensi

-   **MUST / WAJIB:** persyaratan wajib untuk implementasi.
-   **SHOULD / SEBAIKNYA:** rekomendasi kuat; penyimpangan harus
    memiliki alasan teknis.
-   **MAY / OPSIONAL:** dapat dimasukkan berdasarkan prioritas dan
    kapasitas.
-   **Source of truth:** data persisten utama berada di PostgreSQL
    Supabase.
-   **Artifact:** output berversi seperti brief, script, storyboard,
    timeline, voice, subtitle, render, dan export.
-   **Render job:** pekerjaan asynchronous yang menghasilkan media
    final.
-   **Scene:** unit narasi dan visual yang dapat diedit/regenerate
    secara terpisah.

## 0.2 Tujuan dokumen

Dokumen ini menetapkan: 1. Product vision, target pengguna, scope, dan
non-goals. 2. Functional dan non-functional requirements. 3. Arsitektur
frontend, backend, AI, media, dan rendering. 4. Database schema dan
relasi. 5. API contracts dan lifecycle. 6. Agent specification dan
prompt engineering. 7. Orchestration, queue, retry, recovery, dan
idempotency. 8. Remotion composition model dan component registry. 9.
Voice, subtitle, asset, audio, dan quality-control pipeline. 10.
Security, privacy, billing, observability, testing, dan release gates.
11. Phased engineering execution plan dan Definition of Done.

------------------------------------------------------------------------

# 1. Product Vision

## 1.1 Ringkasan produk

MotionForge AI adalah platform produksi video berbasis AI yang mengubah
ide, prompt, artikel, brief marketing, materi edukasi, atau dokumen
menjadi video motion graphic siap publikasi.

Satu proyek produksi mencakup: - Prompt understanding dan creative
brief. - Naskah, hook, narasi, CTA, dan fact-checking sesuai sumber yang
diberikan. - Scenario, story arc, storyboard, dan scene plan. - Visual
direction dan pemilihan motion components. - Image/illustration/graphic
asset management. - Voice-over generation dan audio mastering. -
Subtitle generation dan audio alignment. - Timeline compilation. -
Remotion composition dan preview. - Asynchronous rendering, quality
control, export, dan delivery. - Editing, versioning, selective
regeneration, dan project history.

## 1.2 Product promise

**One brief → One structured production plan → Editable motion graphic
project → Rendered video.**

AI bertindak sebagai creative production team, sedangkan Remotion
bertindak sebagai deterministic composition dan rendering engine. Model
AI tidak menghasilkan kode executable bebas untuk dieksekusi oleh
renderer.

## 1.3 Target pengguna

1.  Content creator dan social media team.
2.  Marketing dan brand team.
3.  Perusahaan/UMKM yang membuat product explainer.
4.  Tim edukasi dan pelatihan.
5.  Agency dan production house.
6.  Tim internal perusahaan yang membuat presentation video.
7.  Enterprise yang membutuhkan template dan brand governance.

## 1.4 Use cases utama

-   Video explainer 30--180 detik.
-   Video edukasi dan microlearning.
-   Infografis animasi.
-   Corporate profile dan product introduction.
-   Marketing campaign dan social content.
-   Data/statistic storytelling.
-   Investor/business presentation video.
-   Multi-format adaptation dari satu project.
-   Multi-language voice-over dan subtitle.

## 1.5 Production modes

  -----------------------------------------------------------------------
  Mode                    Karakter                Output
  ----------------------- ----------------------- -----------------------
  Motion Graphic          Typography, shape,      Video animasi grafis
                          chart, icon, 2D/3D      

  Explainer               Narasi, visual          Video penjelasan
                          storytelling, scene     
                          illustration            

  Presentation            Slide-like scene, data, Video presentasi
                          speaker narration       

  Social Short            Hook cepat, vertical    Reels/Shorts/TikTok
                          composition, captions   

  Documentary-lite        Story-led scenes,       Video informatif
                          footage/illustration    
  -----------------------------------------------------------------------

## 1.6 Non-goals untuk MVP

-   Open-ended video generation berbasis diffusion sebagai core
    renderer.
-   Menjalankan JavaScript/React yang ditulis bebas oleh pengguna atau
    LLM.
-   Full nonlinear editor setara aplikasi desktop profesional.
-   Real-time collaborative frame-level editing.
-   Marketplace publik untuk menjual template pada MVP.
-   Voice cloning tanpa consent dan verifikasi hak suara.
-   Automatic publishing ke semua social networks pada MVP.
-   Menjanjikan factual accuracy tanpa sumber atau review manusia.
-   Menganggap generated image/video otomatis bebas hak cipta.

------------------------------------------------------------------------

# 2. Product Scope dan Prioritas

## 2.1 MVP --- wajib

1.  Authentication, profile, workspace, dan project CRUD.
2.  Prompt Studio dengan pilihan bahasa, durasi, rasio, style, dan
    voice.
3.  AI generation: brief, script, scenario, storyboard, dan scene plan.
4.  Structured schema validation dan versioning.
5.  Scene editor dasar: edit text, duration, layout preset, asset, dan
    order.
6.  Voice-over TTS melalui provider adapter.
7.  Subtitle dengan timestamp dan editor dasar.
8.  Motion component registry yang aman.
9.  Remotion Player preview.
10. Render queue dan dedicated Remotion worker.
11. MP4 export dan thumbnail.
12. Job status, retry, cancel, dan progress.
13. Usage metering dan cost estimate.
14. RLS, audit log, private storage, dan signed URL.
15. Admin configuration untuk template, provider, model, dan quota.

## 2.2 V1 --- setelah MVP stabil

-   Scene-specific regeneration.
-   Brand kit.
-   Multiple aspect ratio adaptation.
-   Music/SFX library dan audio ducking.
-   Multi-language localization.
-   More animation packs.
-   Render variants dan quality profiles.
-   Team collaboration dan approval.
-   Template marketplace internal.
-   Batch production dan project duplication.

## 2.3 V2 --- advanced

-   Enterprise workspaces dan custom template governance.
-   API access dan webhook untuk external customers.
-   Scheduled/batch video production.
-   Advanced timeline editing.
-   Distributed rendering.
-   Template authoring SDK internal.
-   Asset licensing and provenance management.
-   Automated publishing connectors.

------------------------------------------------------------------------

# 3. UX dan Frontend Requirements

## 3.1 Navigation

Customer application: - Dashboard - My Projects - Create Video -
Templates - Brand Kit - Assets - Voice Library - Usage & Billing -
Settings

Project workspace: - Overview - Brief - Script - Storyboard - Assets -
Voice & Audio - Subtitles - Timeline - Preview - Render & Export -
Version History

Admin application: - Users and workspaces - Plans and quotas - LLM
providers and models - TTS providers and voices - Prompt registry -
Motion component registry - Template management - Render workers and
queues - Job failures and retries - Usage and cost analytics - Audit
logs - System configuration

## 3.2 Prompt Studio fields

Wajib: - Prompt/brief. - Production mode. - Output language. - Target
audience. - Video duration target. - Aspect ratio. - Visual style. -
Narration tone. - Voice selection. - Subtitle mode. - Music
preference. - Brand kit (optional). - Source/reference documents
(optional). - CTA (optional). - Factual source policy (optional).

Durasi dan jumlah scene ditentukan secara adaptif. User dapat mengubah
hasil creative brief sebelum generation dilanjutkan.

## 3.3 UX principles

-   Light-first, minimal, professional, responsive, mobile-first.
-   Dark mode option.
-   Clear status and progress; jangan menampilkan progress palsu.
-   Preview harus menggunakan composition yang sama dengan renderer.
-   Setiap AI result dapat direview sebelum tahap mahal berikutnya.
-   Tampilkan estimated cost sebelum generation/render jika estimasi
    tersedia.
-   Perubahan user tidak boleh hilang saat refresh.
-   Autosave dengan optimistic UI yang aman dan conflict handling.
-   Scene-level regeneration tidak boleh menimpa scene lain.
-   Error harus menjelaskan tindakan pemulihan.

## 3.4 Main user journey

1.  User sign-in.
2.  Create project.
3.  Isi prompt dan production settings.
4.  Generate creative brief.
5.  Review dan approve brief.
6.  Generate script.
7.  Edit/approve script.
8.  Generate scenario dan storyboard.
9.  Review/edit scenes.
10. Generate visual assets.
11. Generate voice-over.
12. Generate/alignment subtitle.
13. Compile timeline.
14. Preview video.
15. Request render.
16. Worker render MP4.
17. Quality checks.
18. Deliver video dan thumbnail.
19. User downloads atau creates variant.

Tahap yang memerlukan biaya eksternal harus dapat dikonfigurasi untuk
approval sebelum dijalankan.

------------------------------------------------------------------------

# 4. System Architecture

## 4.1 Logical architecture

``` mermaid
flowchart TB
  U[Customer / Admin] --> WEB[Next.js Web Apps]
  WEB --> API[FastAPI API Gateway]
  API --> AUTH[Supabase Auth Validation]
  API --> DB[(Supabase PostgreSQL)]
  API --> ORCH[Production Orchestrator]
  ORCH --> LLM[LLM Gateway / Model Router]
  ORCH --> DB[(Supabase PostgreSQL Job Queue)]
  ORCH --> MEDIA[Media & Voice Services]
  MEDIA --> STORAGE[(Supabase Storage)]
  DB --> AIW[AI Worker]
  DB --> MW[Media Worker]
  DB --> RW[Remotion Render Worker]
  AIW --> LLM
  AIW --> DB
  MW --> TTS[TTS / Alignment / FFmpeg]
  MW --> STORAGE
  RW --> REM[Remotion Composition Runtime]
  REM --> STORAGE
  RW --> DB
  API --> RT[Supabase Realtime]
  RT --> WEB
```

## 4.2 Service boundaries

### Frontend

-   Next.js customer dashboard dan admin dashboard.
-   React/TypeScript.
-   Remotion Player untuk preview.
-   Typed API client.
-   Tidak mengakses Supabase database secara langsung untuk business
    operations.
-   Supabase Auth client boleh digunakan untuk authentication session
    sesuai security design.

### FastAPI

-   Public API dan internal service API.
-   Authentication token verification.
-   Authorization dan tenant scoping.
-   Project/business logic.
-   Orchestration control plane.
-   Provider abstraction.
-   Billing/usage enforcement.
-   Webhook receiver.
-   Audit logging.

### AI worker

-   Menjalankan agent task.
-   LLM calls.
-   Structured output parsing.
-   Schema validation.
-   Prompt version pinning.
-   Checkpoint dan task result persistence.

### Media worker

-   TTS generation.
-   Audio conversion/normalization.
-   Alignment/transcription.
-   Subtitle packaging.
-   Image metadata and validation.
-   FFmpeg media processing.

### Remotion worker

-   Node.js runtime.
-   Remotion bundle dan registered compositions.
-   Chromium/browser dependencies jika diperlukan oleh renderer.
-   FFmpeg dependencies.
-   Render concurrency control.
-   Render output validation.
-   Upload hasil ke Supabase Storage.

### PostgreSQL job queue

-   Job state dan antrean durable berada di Supabase PostgreSQL.
-   Workers melakukan claim secara transaksional dengan `FOR UPDATE SKIP LOCKED`, lease owner, heartbeat, retry dan expired-lease recovery.
-   Worker polling melalui FastAPI; tidak diperlukan broker eksternal atau Redis.
-   Idempotency dan job lifecycle tetap dicatat di PostgreSQL.

## 4.3 Recommended repository structure

``` text
motionforge/
├── apps/
│   ├── web/                     # Customer Next.js application
│   ├── admin/                   # Admin Next.js application
│   ├── api/                     # FastAPI
│   └── remotion-studio/         # Remotion compositions and Player
├── services/
│   ├── ai-worker/               # Agent execution
│   ├── media-worker/            # TTS, alignment, FFmpeg
│   └── render-worker/           # Node.js Remotion renderer
├── packages/
│   ├── contracts/               # Shared JSON schemas / TS types
│   ├── motion-components/       # Safe registered components
│   ├── motion-presets/          # Animation presets
│   ├── composition-runtime/     # Timeline-to-Remotion adapter
│   ├── api-client/              # Generated/typed client
│   ├── design-system/           # UI tokens and components
│   └── test-fixtures/            # Non-production test fixtures
├── infra/
│   ├── docker/
│   ├── railway/
│   ├── vercel/
│   ├── migrations/
│   └── monitoring/
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── schemas/
│   └── runbooks/
├── .github/workflows/
└── README.md
```

## 4.4 Runtime rules

-   FastAPI dan Remotion renderer berjalan sebagai service berbeda.
-   Remotion renderer tidak menerima arbitrary source code dari client.
-   Composition hanya dapat memilih komponen yang terdaftar.
-   Semua external provider dipanggil melalui adapter.
-   Secrets hanya berada di server-side secret manager/environment.
-   Signed storage URLs memiliki expiry dan scope terbatas.
-   Semua worker harus idempotent dan dapat melanjutkan dari persisted
    checkpoint.
-   Internal service endpoints harus authenticated dan tidak diekspos
    publik tanpa kebutuhan.

------------------------------------------------------------------------

# 5. Domain Model dan Data Contracts

## 5.1 Core entities

-   Workspace: tenant atau ruang kerja.
-   Membership: hubungan user dengan workspace dan role.
-   Project: wadah satu produksi video.
-   Production run: satu eksekusi pipeline.
-   Artifact version: versi immutable dari script/storyboard/timeline.
-   Scene: unit visual dan naratif.
-   Asset: file media atau reference.
-   Voice generation: output TTS.
-   Subtitle track: kumpulan caption.
-   Timeline: susunan track dan clip.
-   Render job: satu permintaan render.
-   Render attempt: percobaan worker.
-   Render artifact: output final/preview.
-   Usage ledger: catatan debit/credit dan cost.
-   Provider/model: konfigurasi LLM/TTS/media provider.

## 5.2 Global conventions

-   Primary keys: UUID.
-   Timestamp: `timestamptz` UTC.
-   Durations: milliseconds pada API/domain; frames pada render
    compilation.
-   Currency: integer minor units atau decimal fixed precision; jangan
    gunakan floating point untuk billing.
-   Asset path: storage object key, bukan public URL permanen.
-   All tenant-owned records carry `workspace_id` where applicable.
-   Soft delete hanya untuk entity yang memerlukan recovery; retention
    policy harus jelas.
-   Immutable artifacts tidak di-update in place; buat versi baru.

## 5.3 Production status enums

Project status: `draft`, `active`, `archived`, `deleted`.

Production run status: `queued`, `planning`, `scripting`,
`storyboarding`, `asset_generation`, `audio_generation`,
`subtitle_generation`, `timeline_compilation`, `ready_for_review`,
`render_queued`, `rendering`, `quality_check`, `completed`, `failed`,
`cancel_requested`, `cancelled`.

Task status: `pending`, `queued`, `running`, `succeeded`, `failed`,
`retry_wait`, `cancelled`, `skipped`.

Render status: `queued`, `preparing`, `rendering`, `uploading`,
`validating`, `completed`, `failed`, `cancel_requested`, `cancelled`.

------------------------------------------------------------------------

# 6. Supabase Database Specification

Database migrations harus version-controlled. Gunakan schema `public`
untuk domain tables atau schema terpisah sesuai governance. Contoh
berikut menggunakan `public`.

## 6.1 Identity and workspace

### `profiles`

-   `id uuid primary key references auth.users(id) on delete cascade`
-   `display_name text`
-   `avatar_path text`
-   `locale text not null default 'id-ID'`
-   `timezone text not null default 'Asia/Jakarta'`
-   `created_at timestamptz not null default now()`
-   `updated_at timestamptz not null default now()`

### `workspaces`

-   `id uuid primary key default gen_random_uuid()`
-   `name text not null`
-   `slug text unique not null`
-   `owner_user_id uuid not null references profiles(id)`
-   `plan_id uuid null`
-   `settings jsonb not null default '{}'`
-   `created_at`, `updated_at timestamptz`

### `workspace_members`

-   `id uuid primary key`
-   `workspace_id uuid not null references workspaces(id)`
-   `user_id uuid not null references profiles(id)`
-   `role text not null check (role in ('owner','admin','editor','viewer','billing'))`
-   `status text not null default 'active'`
-   `created_at timestamptz`
-   Unique `(workspace_id,user_id)`.

## 6.2 Project and creative artifacts

### `video_projects`

-   `id uuid primary key`
-   `workspace_id uuid not null references workspaces(id)`
-   `created_by uuid not null references profiles(id)`
-   `name text not null`
-   `description text`
-   `production_mode text not null`
-   `status text not null default 'draft'`
-   `default_language text not null default 'id-ID'`
-   `target_duration_ms integer`
-   `aspect_ratio text not null default '16:9'`
-   `width integer not null default 1920`
-   `height integer not null default 1080`
-   `fps integer not null default 30`
-   `brand_kit_id uuid null`
-   `active_run_id uuid null`
-   `created_at`, `updated_at timestamptz`
-   Index `(workspace_id, updated_at desc)`.

### `project_settings`

-   `project_id uuid primary key references video_projects(id)`
-   `settings jsonb not null default '{}'`
-   `version integer not null default 1`
-   `updated_at timestamptz`

### `creative_briefs`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `version integer not null`
-   `input_prompt text not null`
-   `normalized_brief jsonb not null`
-   `source_references jsonb not null default '[]'`
-   `approved_by uuid null`
-   `approved_at timestamptz null`
-   `created_at timestamptz`
-   Unique `(project_id,version)`.

### `video_scripts`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `production_run_id uuid null`
-   `version integer not null`
-   `language text not null`
-   `title text not null`
-   `hook text`
-   `body jsonb not null`
-   `cta text`
-   `estimated_duration_ms integer`
-   `word_count integer`
-   `status text not null default 'draft'`
-   `created_by_agent text`
-   `created_at timestamptz`
-   Unique `(project_id,version)`.

### `storyboards`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `script_id uuid not null references video_scripts(id)`
-   `version integer not null`
-   `global_visual_direction jsonb not null`
-   `status text not null default 'draft'`
-   `created_at timestamptz`
-   Unique `(project_id,version)`.

### `storyboard_scenes`

-   `id uuid primary key`
-   `storyboard_id uuid not null references storyboards(id) on delete cascade`
-   `scene_index integer not null`
-   `title text not null`
-   `purpose text`
-   `narration_text text`
-   `duration_ms integer not null`
-   `visual_direction jsonb not null`
-   `transition_in text`
-   `transition_out text`
-   `motion_plan jsonb not null`
-   `asset_requirements jsonb not null default '[]'`
-   `created_at`, `updated_at`
-   Unique `(storyboard_id,scene_index)`.

### `artifact_versions`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `artifact_type text not null`
-   `artifact_id uuid not null`
-   `version integer not null`
-   `content_hash text not null`
-   `created_by uuid null`
-   `created_by_agent text null`
-   `change_summary text`
-   `created_at timestamptz`
-   Unique `(project_id,artifact_type,artifact_id,version)`.

## 6.3 Orchestration

### `production_runs`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `workspace_id uuid not null references workspaces(id)`
-   `requested_by uuid not null references profiles(id)`
-   `status text not null`
-   `current_stage text`
-   `progress_percent numeric(5,2) not null default 0`
-   `input_snapshot jsonb not null`
-   `config_snapshot jsonb not null`
-   `idempotency_key text not null`
-   `error_code text`
-   `error_message_safe text`
-   `started_at timestamptz`
-   `completed_at timestamptz`
-   `created_at timestamptz`
-   Unique `(workspace_id,idempotency_key)`.

### `agent_tasks`

-   `id uuid primary key`
-   `production_run_id uuid not null references production_runs(id)`
-   `parent_task_id uuid null references agent_tasks(id)`
-   `agent_key text not null`
-   `task_type text not null`
-   `status text not null`
-   `input_artifact_id uuid null`
-   `output_artifact_id uuid null`
-   `input_payload jsonb not null`
-   `output_payload jsonb`
-   `prompt_version_id uuid null`
-   `model_config_snapshot jsonb`
-   `attempt_count integer not null default 0`
-   `max_attempts integer not null default 3`
-   `lease_expires_at timestamptz`
-   `started_at`, `completed_at`, `created_at timestamptz`
-   `error_code text`
-   `error_detail_internal text`
-   Index `(production_run_id,status)`.

### `workflow_checkpoints`

-   `id uuid primary key`
-   `production_run_id uuid not null references production_runs(id)`
-   `stage_key text not null`
-   `checkpoint_key text not null`
-   `payload jsonb not null`
-   `content_hash text not null`
-   `created_at timestamptz`
-   Unique `(production_run_id,checkpoint_key)`.

### `workflow_events`

-   `id uuid primary key`
-   `production_run_id uuid not null references production_runs(id)`
-   `event_type text not null`
-   `event_payload jsonb not null`
-   `sequence_number bigint not null`
-   `created_at timestamptz`
-   Unique `(production_run_id,sequence_number)`.

## 6.4 Media and assets

### `media_assets`

-   `id uuid primary key`
-   `workspace_id uuid not null references workspaces(id)`
-   `project_id uuid null references video_projects(id)`
-   `uploaded_by uuid null references profiles(id)`
-   `asset_type text not null`
-   `source_type text not null`
-   `storage_bucket text not null`
-   `storage_path text not null`
-   `original_filename text`
-   `mime_type text not null`
-   `file_size_bytes bigint not null`
-   `width integer`
-   `height integer`
-   `duration_ms integer`
-   `checksum_sha256 text`
-   `license_metadata jsonb not null default '{}'`
-   `provenance jsonb not null default '{}'`
-   `status text not null default 'available'`
-   `created_at timestamptz`
-   Unique `(storage_bucket,storage_path)`.

### `asset_usage`

-   `id uuid primary key`
-   `asset_id uuid not null references media_assets(id)`
-   `project_id uuid not null references video_projects(id)`
-   `scene_id uuid null references storyboard_scenes(id)`
-   `usage_type text not null`
-   `created_at timestamptz`.

### `brand_kits`

-   `id uuid primary key`
-   `workspace_id uuid not null references workspaces(id)`
-   `name text not null`
-   `logo_asset_id uuid null references media_assets(id)`
-   `colors jsonb not null`
-   `fonts jsonb not null`
-   `guidelines jsonb not null default '{}'`
-   `created_at`, `updated_at timestamptz`.

### `audio_generations`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `scene_id uuid null references storyboard_scenes(id)`
-   `provider_key text not null`
-   `voice_key text not null`
-   `input_text text not null`
-   `storage_asset_id uuid null references media_assets(id)`
-   `duration_ms integer`
-   `alignment_data jsonb`
-   `generation_config jsonb not null`
-   `status text not null`
-   `created_at timestamptz`.

### `subtitle_tracks`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `language text not null`
-   `format text not null default 'json'`
-   `style_config jsonb not null`
-   `version integer not null`
-   `status text not null`
-   `created_at timestamptz`
-   Unique `(project_id,language,version)`.

### `subtitle_segments`

-   `id uuid primary key`
-   `track_id uuid not null references subtitle_tracks(id) on delete cascade`
-   `segment_index integer not null`
-   `text text not null`
-   `start_ms integer not null`
-   `end_ms integer not null`
-   `word_timings jsonb`
-   `emphasis jsonb`
-   Check `end_ms > start_ms`
-   Unique `(track_id,segment_index)`.

## 6.5 Timeline and Remotion

### `video_timelines`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `version integer not null`
-   `fps integer not null`
-   `width integer not null`
-   `height integer not null`
-   `duration_frames integer not null`
-   `timeline_json jsonb not null`
-   `compiled_hash text not null`
-   `status text not null`
-   `created_at timestamptz`
-   Unique `(project_id,version)`.

### `timeline_tracks`

-   `id uuid primary key`
-   `timeline_id uuid not null references video_timelines(id) on delete cascade`
-   `track_key text not null`
-   `track_type text not null`
-   `z_index integer not null`
-   `config jsonb not null default '{}'`
-   Unique `(timeline_id,track_key)`.

### `timeline_clips`

-   `id uuid primary key`
-   `track_id uuid not null references timeline_tracks(id) on delete cascade`
-   `scene_id uuid null references storyboard_scenes(id)`
-   `clip_type text not null`
-   `start_frame integer not null`
-   `duration_frames integer not null`
-   `component_key text`
-   `props jsonb not null default '{}'`
-   `asset_id uuid null references media_assets(id)`
-   `created_at timestamptz`
-   Check `start_frame >= 0`
-   Check `duration_frames > 0`.

### `motion_components`

-   `id uuid primary key`
-   `component_key text unique not null`
-   `display_name text not null`
-   `category text not null`
-   `version text not null`
-   `props_schema jsonb not null`
-   `default_props jsonb not null`
-   `capabilities jsonb not null`
-   `is_enabled boolean not null default true`
-   `created_at`, `updated_at timestamptz`.

### `composition_templates`

-   `id uuid primary key`
-   `template_key text unique not null`
-   `name text not null`
-   `description text`
-   `version text not null`
-   `supported_ratios jsonb not null`
-   `config_schema jsonb not null`
-   `is_published boolean not null default false`
-   `created_at`, `updated_at timestamptz`.

## 6.6 Rendering and exports

### `render_jobs`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `workspace_id uuid not null references workspaces(id)`
-   `timeline_id uuid not null references video_timelines(id)`
-   `requested_by uuid not null references profiles(id)`
-   `status text not null`
-   `priority integer not null default 0`
-   `idempotency_key text not null`
-   `render_config jsonb not null`
-   `progress_percent numeric(5,2) not null default 0`
-   `worker_id text`
-   `attempt_count integer not null default 0`
-   `max_attempts integer not null default 2`
-   `error_code text`
-   `error_message_safe text`
-   `queued_at`, `started_at`, `completed_at timestamptz`
-   `created_at timestamptz`
-   Unique `(workspace_id,idempotency_key)`.

### `render_attempts`

-   `id uuid primary key`
-   `render_job_id uuid not null references render_jobs(id)`
-   `attempt_number integer not null`
-   `worker_id text`
-   `status text not null`
-   `started_at`, `ended_at timestamptz`
-   `logs_path text`
-   `diagnostics jsonb`
-   `error_code text`
-   Unique `(render_job_id,attempt_number)`.

### `render_artifacts`

-   `id uuid primary key`
-   `render_job_id uuid not null references render_jobs(id)`
-   `artifact_type text not null`
-   `storage_bucket text not null`
-   `storage_path text not null`
-   `mime_type text not null`
-   `file_size_bytes bigint`
-   `duration_ms integer`
-   `width integer`
-   `height integer`
-   `checksum_sha256 text`
-   `created_at timestamptz`.

### `video_exports`

-   `id uuid primary key`
-   `project_id uuid not null references video_projects(id)`
-   `render_artifact_id uuid not null references render_artifacts(id)`
-   `format text not null`
-   `aspect_ratio text not null`
-   `created_by uuid not null references profiles(id)`
-   `created_at timestamptz`.

## 6.7 Model, prompts, usage, and governance

### `ai_providers`

-   `id uuid primary key`
-   `provider_key text unique not null`
-   `display_name text not null`
-   `provider_type text not null`
-   `is_enabled boolean not null default false`
-   `config_public jsonb not null default '{}'`
-   Secret credentials live in secret manager, not this table.

### `ai_models`

-   `id uuid primary key`
-   `provider_id uuid not null references ai_providers(id)`
-   `model_key text not null`
-   `capabilities jsonb not null`
-   `cost_config jsonb not null`
-   `is_enabled boolean not null default false`
-   Unique `(provider_id,model_key)`.

### `prompt_templates`

-   `id uuid primary key`
-   `prompt_key text not null`
-   `version integer not null`
-   `agent_key text not null`
-   `system_prompt text not null`
-   `user_template text not null`
-   `output_schema jsonb not null`
-   `status text not null`
-   `created_at timestamptz`
-   Unique `(prompt_key,version)`.

### `model_usage`

-   `id uuid primary key`
-   `workspace_id uuid not null references workspaces(id)`
-   `project_id uuid null references video_projects(id)`
-   `production_run_id uuid null references production_runs(id)`
-   `agent_task_id uuid null references agent_tasks(id)`
-   `provider_key text not null`
-   `model_key text not null`
-   `input_tokens bigint`
-   `output_tokens bigint`
-   `estimated_cost_minor bigint`
-   `actual_cost_minor bigint`
-   `currency text not null`
-   `created_at timestamptz`.

### `usage_ledger`

-   `id uuid primary key`
-   `workspace_id uuid not null references workspaces(id)`
-   `user_id uuid null references profiles(id)`
-   `reference_type text not null`
-   `reference_id uuid not null`
-   `entry_type text not null`
-   `quantity numeric(18,6) not null`
-   `unit text not null`
-   `amount_minor bigint not null default 0`
-   `currency text not null`
-   `idempotency_key text unique not null`
-   `metadata jsonb not null default '{}'`
-   `created_at timestamptz`.

### `audit_logs`

-   `id uuid primary key`
-   `workspace_id uuid null`
-   `actor_user_id uuid null`
-   `action text not null`
-   `resource_type text not null`
-   `resource_id uuid null`
-   `metadata_redacted jsonb not null default '{}'`
-   `ip_hash text`
-   `created_at timestamptz`.

## 6.8 Database implementation rules

1.  Semua tabel tenant-owned harus memiliki `workspace_id` secara
    langsung atau melalui relasi yang dapat divalidasi.
2.  RLS harus aktif pada seluruh tabel yang dapat diakses client.
3.  Worker/service-role hanya digunakan server-side.
4.  Jangan mengandalkan UUID sulit ditebak sebagai authorization.
5.  RLS policy memeriksa membership aktif dan role yang sesuai.
6.  Mutasi multi-tabel kritis dilakukan melalui transaction/RPC
    terkontrol atau backend transaction.
7.  Render request harus mengunci snapshot timeline yang immutable.
8.  Usage debit harus idempotent dan transactional.
9.  Storage object path harus mencakup workspace/project scope.
10. Index dibuat untuk foreign keys, status, created_at, workspace, dan
    queue lookup.
11. Tambahkan retention/cleanup untuk temporary artifacts dan abandoned
    uploads.
12. Buat migration tests untuk memastikan schema dapat dibangun dari
    database kosong dan upgrade dari versi sebelumnya.

## 6.9 RLS policy model

-   `owner`: seluruh resource workspace.
-   `admin`: manage members/settings/projects dan view billing sesuai
    permission.
-   `editor`: create/update project artifacts dan request
    generation/render.
-   `viewer`: read-only project access.
-   `billing`: read usage/invoices dan manage billing; tidak otomatis
    dapat mengubah video.
-   Service worker: akses terbatas melalui server-side service role dan
    internal authorization.

Jangan membuat policy berbasis `user_id` saja untuk resource workspace.
Validasi `workspace_members` harus menjadi sumber otorisasi tenant.

------------------------------------------------------------------------

# 7. API Contract Specification

## 7.1 API conventions

Base path: `/api/v1`

Headers: - `Authorization: Bearer <supabase_access_token>` -
`Content-Type: application/json` - `Idempotency-Key: <unique-key>` untuk
operasi asynchronous/mutating yang berpotensi diulang. - `X-Request-ID`
optional client correlation ID.

Response envelope:
``` json
{
  "data": {},
  "meta": {
    "request_id": "uuid",
    "version": "v1"
  },
  "error": null
}
```

Error envelope:

``` json
{
  "data": null,
  "meta": {"request_id": "uuid"},
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request tidak valid.",
    "details": []
  }
}
```

HTTP status: - `200`: read/update success. - `201`: created. - `202`:
asynchronous job accepted. - `204`: successful no-content. - `400`:
invalid business request. - `401`: unauthenticated. - `403`:
unauthorized. - `404`: resource not found or not visible. - `409`:
state/version conflict. - `422`: schema validation error. - `429`:
rate/quota limit. - `500`: unexpected server error. - `503`: dependency
unavailable.

## 7.2 Endpoint catalogue

### Authentication and workspace

-   `GET /me`
-   `GET /workspaces`
-   `POST /workspaces`
-   `GET /workspaces/{workspace_id}`
-   `PATCH /workspaces/{workspace_id}`
-   `GET /workspaces/{workspace_id}/members`
-   `POST /workspaces/{workspace_id}/members`
-   `PATCH /workspaces/{workspace_id}/members/{member_id}`

### Projects

-   `GET /projects?workspace_id=&cursor=&limit=`
-   `POST /projects`
-   `GET /projects/{project_id}`
-   `PATCH /projects/{project_id}`
-   `DELETE /projects/{project_id}`
-   `POST /projects/{project_id}/duplicate`
-   `GET /projects/{project_id}/versions`

### Creative production

-   `POST /projects/{project_id}/briefs/generate`
-   `GET /projects/{project_id}/briefs`
-   `POST /projects/{project_id}/briefs/{brief_id}/approve`
-   `POST /projects/{project_id}/scripts/generate`
-   `GET /projects/{project_id}/scripts`
-   `PATCH /projects/{project_id}/scripts/{script_id}`
-   `POST /projects/{project_id}/scripts/{script_id}/approve`
-   `POST /projects/{project_id}/storyboards/generate`
-   `GET /projects/{project_id}/storyboards`
-   `PATCH /projects/{project_id}/scenes/{scene_id}`
-   `POST /projects/{project_id}/scenes/{scene_id}/regenerate`

### Assets and audio

-   `POST /projects/{project_id}/assets/upload-intent`
-   `POST /projects/{project_id}/assets/complete-upload`
-   `GET /projects/{project_id}/assets`
-   `POST /projects/{project_id}/assets/generate`
-   `POST /projects/{project_id}/voice/generate`
-   `GET /projects/{project_id}/voice`
-   `POST /projects/{project_id}/subtitles/generate`
-   `GET /projects/{project_id}/subtitles`
-   `PATCH /projects/{project_id}/subtitles/{track_id}`

### Timeline and preview

-   `POST /projects/{project_id}/timeline/compile`
-   `GET /projects/{project_id}/timeline`
-   `PATCH /projects/{project_id}/timeline`
-   `POST /projects/{project_id}/timeline/validate`
-   `GET /projects/{project_id}/preview-config`
-   `GET /motion-components`
-   `GET /composition-templates`

### Rendering and export

-   `POST /projects/{project_id}/renders`
-   `GET /renders/{render_id}`
-   `POST /renders/{render_id}/cancel`
-   `POST /renders/{render_id}/retry`
-   `GET /projects/{project_id}/renders`
-   `GET /renders/{render_id}/artifacts`
-   `POST /exports/{artifact_id}/download-url`

### Usage and admin

-   `GET /usage/summary`
-   `GET /usage/ledger`
-   `GET /billing/plans`
-   `GET /admin/providers`
-   `PATCH /admin/providers/{provider_id}`
-   `GET /admin/models`
-   `PATCH /admin/models/{model_id}`
-   `GET /admin/prompts`
-   `POST /admin/prompts`
-   `POST /admin/prompts/{prompt_id}/publish`
-   `GET /admin/render-workers`
-   `GET /admin/render-jobs`
-   `GET /admin/audit-logs`

## 7.3 Key request contracts

### Create project

`POST /api/v1/projects`

``` json
{
  "workspace_id": "uuid",
  "name": "AI Explainer Indonesia",
  "production_mode": "motion_graphic",
  "language": "id-ID",
  "target_duration_ms": 60000,
  "aspect_ratio": "16:9",
  "visual_style": "modern_cinematic"
}
```

### Generate creative brief

`POST /api/v1/projects/{id}/briefs/generate`

``` json
{
  "prompt": "Buat video tentang perkembangan AI di Indonesia.",
  "audience": "general",
  "objective": "education",
  "language": "id-ID",
  "duration_ms": 60000,
  "aspect_ratio": "16:9",
  "visual_style": "modern_cinematic",
  "narration": {
    "voice_profile_id": null,
    "tone": "inspiring",
    "pace": "medium"
  },
  "subtitle": {
    "enabled": true,
    "mode": "sentence"
  },
  "music": {
    "enabled": true,
    "mood": "inspiring"
  },
  "approval_mode": "review_each_stage"
}
```

Response `202`:

``` json
{
  "data": {
    "production_run_id": "uuid",
    "status": "queued",
    "events_url": "/api/v1/production-runs/uuid/events"
  },
  "meta": {"request_id": "uuid"},
  "error": null
}
```

### Render request

`POST /api/v1/projects/{id}/renders`

``` json
{
  "timeline_id": "uuid",
  "output": {
    "format": "mp4",
    "codec": "h264",
    "quality": "high",
    "width": 1920,
    "height": 1080,
    "fps": 30
  },
  "include_thumbnail": true,
  "include_subtitles": {
    "burn_in": true,
    "sidecar_formats": ["srt", "vtt"]
  }
}
```

Response `202` returns render job ID and status URL.

## 7.4 Version and concurrency

-   PATCH artifact harus menerima `If-Match` atau `expected_version`.
-   Jika versi tidak cocok, return `409 VERSION_CONFLICT`.
-   Render harus menunjuk `timeline_id` immutable/versioned.
-   User edits menghasilkan artifact version baru.
-   Jangan mengubah timeline yang sedang dirender.
-   Regeneration menggunakan parent artifact/version reference.

## 7.5 Realtime events

Supabase Realtime atau authenticated SSE dapat mengirim: -
`production.run.created` - `production.stage.started` -
`production.stage.progress` - `production.stage.completed` -
`agent.task.failed` - `asset.created` - `voice.completed` -
`subtitle.completed` - `timeline.compiled` - `render.queued` -
`render.progress` - `render.completed` - `render.failed` -
`render.cancelled`

Event payload minimum: `event_id`, `workspace_id`, `project_id`,
`run_id`, `resource_id`, `event_type`, `sequence`, `occurred_at`,
`payload`.

Client harus melakukan reconnect dan fetch authoritative status dari
API; jangan menganggap event stream sebagai source of truth.

------------------------------------------------------------------------

# 8. AI Agent Specification

## 8.1 Agent design principles

1.  Agent memiliki satu tanggung jawab yang sempit.
2.  Input/output didefinisikan melalui JSON schema.
3.  Agent tidak memiliki akses database bebas; tool access melalui
    service interface.
4.  Agent tidak mengeksekusi kode yang dihasilkan.
5.  Agent output harus divalidasi secara deterministik.
6.  Setiap output mencatat prompt version, model, usage, dan provenance.
7.  Agent boleh meminta clarification jika brief tidak cukup.
8.  Human approval dapat menjadi gate sebelum cost-intensive stages.
9.  Agent harus menghormati user constraints dan source material.
10. Retry hanya untuk error transient; schema failures dapat meminta
    constrained repair.

## 8.2 Agent roster

### A01 --- Prompt Interpreter

**Objective:** Mengubah prompt mentah menjadi normalized creative brief.

Input: - User prompt. - Project settings. - Workspace brand
guidelines. - Source documents/references.

Output: - Objective. - Audience. - Key message. - Tone. - Language. -
Duration target. - Production mode. - Visual style. - CTA. -
Constraints. - Missing information/questions. - Risk flags.

Tools: - Read project settings. - Read brand kit. - Read source
metadata.

Tidak boleh: - Membuat klaim faktual baru tanpa sumber. - Mengubah
instruksi user yang eksplisit. - Mengasumsikan brand asset yang tidak
tersedia.

### A02 --- Research & Fact Structuring Agent

**Objective:** Mengorganisasi fakta dari dokumen/sumber yang diberikan.

Output: - Claims. - Evidence references. - Source excerpts/locations. -
Confidence labels. - Unverified claims.

Rules: - Jika user tidak memberikan sumber dan factual claim memerlukan
data terkini, tandai sebagai perlu verifikasi. - Jangan menciptakan
statistik. - Bedakan opini, estimasi, dan fakta. - Pertahankan
provenance.

MVP dapat menggunakan source material user saja; web research adalah
capability terpisah yang harus memiliki permission dan citation
handling.

### A03 --- Scriptwriter Agent

**Objective:** Membuat script yang sesuai durasi dan tujuan.

Output: - Title. - Hook. - Narration segments. - On-screen text. - Scene
intent. - CTA. - Estimated spoken duration. - Pronunciation hints.

Rules: - Script harus dapat diucapkan secara natural. - Hindari kalimat
terlalu panjang. - Estimasi durasi berdasarkan word count dan speech
rate yang dapat dikonfigurasi. - Jangan menambahkan klaim di luar
evidence pack tanpa penanda.

### A04 --- Story Director Agent

**Objective:** Membuat narrative arc dan scene structure.

Output: - Opening. - Context. - Main points. - Transition logic. -
Climax/insight. - Closing. - Scene sequence.

Rules: - Setiap scene memiliki satu fungsi utama. - Scene harus memiliki
hubungan naratif. - Durasi total harus mendekati target dalam tolerance
yang ditentukan. - Jangan membuat scene filler hanya untuk mencapai
jumlah tertentu.

### A05 --- Storyboard Agent

**Objective:** Menerjemahkan script menjadi storyboard per scene.

Output per scene: - Scene purpose. - Narration segment IDs. - On-screen
text. - Visual description. - Layout. - Asset requirements. - Motion
component candidates. - Transition. - Start/duration estimate.

Rules: - Scene harus bisa diproduksi dengan komponen yang tersedia. -
Jika visual membutuhkan asset eksternal, buat asset request eksplisit. -
Jangan menyatakan asset sudah ada sebelum asset registry mengonfirmasi.

### A06 --- Visual Director Agent

**Objective:** Memilih visual system dan registered components.

Output: - Palette tokens. - Typography tokens. - Layout preset. -
Component keys. - Animation preset keys. - Transition keys. - Visual
hierarchy. - Safe-area constraints.

Rules: - Hanya memilih component keys dari registry aktif. - Props harus
sesuai schema. - Dilarang menghasilkan arbitrary React/JS code. -
Hormati brand kit dan contrast requirements.

### A07 --- Asset Planner / Asset Generation Agent

**Objective:** Menentukan asset yang perlu dicari, diunggah, dibuat,
atau digunakan ulang.

Output: - Asset request list. - Prompt per asset jika image generation
provider diaktifkan. - Aspect ratio. - Transparency requirement. -
License/provenance requirement. - Scene usage mapping.

Rules: - Cek reusable asset terlebih dahulu. - Jangan mengulang
generation jika checksum/semantic match memadai. - Asset yang tidak
memiliki usage rights harus diblokir dari commercial export. - Simpan
provenance provider dan prompt.

### A08 --- Voice Director Agent

**Objective:** Mengatur voice delivery.

Output: - Voice profile. - Language. - Tone. - Emotion. - Pace. -
Pronunciation dictionary. - Segment boundaries. - Pause instructions.

Rules: - Voice profile harus tersedia dan diizinkan. - Voice cloning
hanya jika consent dan hak penggunaan telah diverifikasi. - Provider
limitations harus ditampilkan.

### A09 --- Subtitle & Alignment Agent

**Objective:** Menghasilkan caption yang sinkron dengan audio.

Output: - Subtitle segments. - Word timings bila tersedia. - Line
breaks. - Emphasis. - Style preset. - SRT/VTT data.

Rules: - Prioritaskan timestamp dari forced alignment/provider. - Jika
hanya tersedia sentence-level timestamps, jangan mengklaim word-level
precision. - Periksa overlap, negative duration, dan readability.

### A10 --- Timeline Compiler

Ini adalah deterministic service, bukan LLM agent.

**Objective:** Compile approved storyboard, assets, audio, subtitles,
dan transitions menjadi timeline schema.

Rules: - Convert milliseconds to frames dengan rounding policy
konsisten. - Validate clip boundaries. - Resolve asset IDs ke authorized
media references. - Ensure component props schema-valid. - Freeze
timeline snapshot sebelum render. - Generate content hash.

### A11 --- Production QA Agent

**Objective:** Menilai kelengkapan creative output dan memberikan QA
findings.

Input: - Brief, script, storyboard, timeline, asset metadata, audio
metadata, render diagnostics.

Output: - Findings severity. - Evidence. - Suggested fixes. - Pass/fail
recommendation.

Deterministic validators tetap menjadi gate utama untuk schema,
duration, missing asset, file integrity, and render checks. LLM QA tidak
boleh menutupi validator failure.

### A12 --- Localization Agent (V1)

**Objective:** Adaptasi script dan subtitle ke bahasa lain.

Rules: - Preserve meaning, names, brand terms, and factual claims. -
Recalculate timing after voice generation. - Do not translate
word-for-word if it becomes unnatural. - Keep source and target artifact
linkage.

------------------------------------------------------------------------

# 9. Prompt Engineering Standard

## 9.1 Prompt registry

Setiap prompt disimpan dengan: - `prompt_key` - `version` -
`agent_key` - `system_prompt` - `user_template` - `output_schema` -
`model_policy` - `temperature/top_p` jika provider mendukung -
`max_output_tokens` - `status`: draft, published, deprecated - changelog
dan test cases.

Production run harus mem-pin prompt version. Perubahan prompt tidak
boleh mengubah run yang sedang berjalan.

## 9.2 Global system prompt principles

Setiap agent prompt harus menyertakan: - Role dan single
responsibility. - Objective. - Trusted input boundaries. - User
constraints. - Output JSON schema. - Prohibited behavior. - Missing
information policy. - Factuality/provenance rules. - Language and
locale. - Length/duration constraints. - No markdown outside JSON bila
strict JSON diminta.

## 9.3 Prompt template --- Prompt Interpreter

``` text
SYSTEM:
You are the Prompt Interpreter for a professional motion-graphic
video production platform.

Convert the user's request into a normalized creative brief.
Do not write the full script or storyboard.
Do not invent facts, metrics, sources, assets, or brand rules.
Preserve explicit user constraints.
If required information is missing, mark it as a question or
a configurable assumption. Never silently invent it.

Return only JSON matching the supplied schema.

USER:
User prompt: {{user_prompt}}
Project settings: {{project_settings}}
Brand kit: {{brand_kit}}
Source references: {{source_references}}
Output language: {{language}}
Duration target: {{duration_ms}}
Production mode: {{production_mode}}
```

## 9.4 Prompt template --- Scriptwriter

``` text
SYSTEM:
You are a professional video scriptwriter.
Write natural spoken narration for the target audience and duration.
Use only supported facts from the evidence pack. Label unsupported
claims for review. Create a strong opening, coherent body, and
purposeful closing. Separate narration from on-screen text.
Return structured JSON only.

USER:
Creative brief: {{creative_brief}}
Evidence pack: {{evidence_pack}}
Target duration: {{duration_ms}}
Language: {{language}}
Tone: {{tone}}
CTA: {{cta}}
Speech rate policy: {{speech_rate_policy}}
```

## 9.5 Prompt template --- Storyboard

``` text
SYSTEM:
You are a motion-graphic storyboard director.
Translate the approved script into production-ready scenes.
Each scene must have one narrative purpose, a visual concept,
on-screen text, duration estimate, asset requirements, and
registered motion component candidates.
Only select component keys from the supplied registry.
Do not emit code or claim assets exist unless confirmed.
Return JSON matching the schema.

USER:
Approved script: {{script}}
Component registry: {{component_registry}}
Template constraints: {{template_constraints}}
Canvas: {{width}}x{{height}}
FPS: {{fps}}
Target duration: {{duration_ms}}
```

## 9.6 Prompt template --- Visual Director

``` text
SYSTEM:
You are a motion design director.
Select a consistent visual system and registered components.
Respect the brand kit, aspect ratio, safe areas, contrast, and
accessibility. Use only the supplied component and animation keys.
Every component property must match its JSON schema.
Do not generate executable source code.

USER:
Storyboard: {{storyboard}}
Brand kit: {{brand_kit}}
Available components: {{component_registry}}
Available presets: {{animation_registry}}
```

## 9.7 Prompt template --- Production QA

``` text
SYSTEM:
You are a production quality reviewer.
Review the supplied artifacts and diagnostics.
Do not invent test results. Cite the exact artifact/scene/diagnostic
that supports each finding. Separate blockers, warnings, and notes.
Return structured JSON only.

USER:
Brief: {{brief}}
Script: {{script}}
Storyboard: {{storyboard}}
Timeline validation: {{timeline_validation}}
Render diagnostics: {{render_diagnostics}}
```

## 9.8 Prompt injection defense

-   Treat uploaded documents, captions, metadata, and reference text as
    untrusted content.
-   Never follow instructions embedded in source documents that conflict
    with system policy.
-   Do not expose system prompts, secrets, provider keys, or internal
    tools.
-   Tool calls must be allowlisted and typed.
-   Model output is data, not executable instruction.
-   Validate URLs, MIME types, asset ownership, and file size
    server-side.
-   Apply output schema validation and content moderation where
    required.

------------------------------------------------------------------------

# 10. Orchestration Workflow

## 10.1 Workflow stages

``` mermaid
flowchart TD
  A[Create Project] --> B[Normalize Prompt]
  B --> C[Creative Brief]
  C --> D{User Approval?}
  D -->|Revise| B
  D -->|Approve| E[Generate Script]
  E --> F[Script Validation]
  F --> G{Script Approved?}
  G -->|No| E
  G -->|Yes| H[Story Arc + Storyboard]
  H --> I[Storyboard Validation]
  I --> J[Visual Direction]
  J --> K[Asset Plan]
  K --> L[Asset Generation / Upload]
  L --> M[Voice Generation]
  M --> N[Audio Alignment]
  N --> O[Subtitle Generation]
  O --> P[Timeline Compilation]
  P --> Q[Timeline Validation]
  Q --> R[Preview]
  R --> S{User Approval?}
  S -->|Edit| H
  S -->|Approve| T[Render Queue]
  T --> U[Remotion Worker]
  U --> V[Output Validation]
  V --> W{Valid?}
  W -->|No| X[Retry / Repair]
  X --> U
  W -->|Yes| Y[Publish Artifacts]
```

## 10.2 Stage contract

Each stage must: 1. Verify prerequisites. 2. Acquire idempotent task
lease. 3. Load immutable input snapshots. 4. Resolve pinned
prompt/model/provider configuration. 5. Execute operation. 6. Validate
output. 7. Persist artifact and usage. 8. Write workflow
event/checkpoint. 9. Mark task success/failure. 10. Enqueue next
eligible stage.

## 10.3 Retry policy

Retry only transient failures: - Provider 429: respect Retry-After and
exponential backoff. - Provider 5xx/network: bounded exponential backoff
with jitter. - Worker interruption: lease expiry and safe requeue. -
Invalid model output: one or more constrained repair attempts, then fail
with actionable error. - Missing user asset: do not retry indefinitely;
request user action. - Invalid schema/business state: fail fast. -
Insufficient quota: stop before paid provider operation.

## 10.4 Idempotency

-   Every user-triggered async operation accepts Idempotency-Key.
-   Unique database constraint prevents duplicate job creation.
-   Provider idempotency keys used where supported.
-   If provider lacks idempotency, store request hash and reconcile
    before retry.
-   Asset uploads use checksum and unique object key.
-   Usage debit uses unique ledger idempotency key.
-   Render output path includes render ID and attempt/version.
-   Duplicate events are ignored using event ID/sequence.

## 10.5 Cancellation

-   User cancellation sets `cancel_requested`.
-   Orchestrator stops scheduling downstream tasks.
-   Worker checks cancellation at safe checkpoints.
-   Remotion render is terminated using supported renderer process
    controls.
-   Partial temporary output is marked and cleaned.
-   Usage policy distinguishes committed provider costs from refundable
    internal credits.
-   Final status becomes `cancelled` only after worker acknowledgement
    or lease recovery.

## 10.6 Recovery

-   Persist stage checkpoint after each successful artifact.
-   Worker lease contains expiry.
-   Recovery scheduler detects stale `running` tasks.
-   Requeue only if operation is safe/idempotent.
-   Rebuild derived state from authoritative records.
-   Never rely only on in-memory process state.
-   Provide admin runbook for stuck job recovery.

------------------------------------------------------------------------

# 11. Remotion Composition and Motion Component Registry

## 11.1 Core principles

-   Remotion is the only core composition/rendering engine.
-   Composition input is a validated, versioned timeline JSON.
-   Component registry is allowlisted.
-   No `eval`, dynamic import from user content, arbitrary JSX, or
    arbitrary package installation.
-   Each component has a stable key, semantic version, schema, default
    props, and test coverage.
-   Preview and render use the same composition code and pinned
    dependencies.

## 11.2 Registry categories

  Category      Component examples
  ------------- ------------------------------------------------------
  Typography    title-reveal, kinetic-words, typewriter, lower-third
  Infographic   stat-counter, bar-chart, line-chart, donut-chart
  Shapes        shape-morph, line-draw, geometric-grid
  Layout        split-screen, card-stack, quote-panel
  Image         image-pan-zoom, parallax-image, masked-image
  2D            icon-sequence, map-highlight, process-flow
  3D            glb-viewer, 3d-product-turntable (optional package)
  Effects       particles, glow, blur, noise, scanline
  Transition    fade, wipe, zoom, slide, match-cut
  Captions      sentence-caption, karaoke-caption, word-highlight
  Audio         narration-track, music-track, sfx-track

## 11.3 Component contract

Example component registry entry:

``` json
{
  "key": "typography.title-reveal",
  "version": "1.0.0",
  "category": "typography",
  "displayName": "Title Reveal",
  "propsSchema": {
    "type": "object",
    "required": ["text", "fontSize", "color"],
    "properties": {
      "text": {"type": "string", "maxLength": 160},
      "fontSize": {"type": "number", "minimum": 12, "maximum": 180},
      "color": {"type": "string"},
      "alignment": {
        "type": "string",
        "enum": ["left", "center", "right"]
      },
      "animationPreset": {
        "type": "string",
        "enum": ["fade-up", "spring-scale", "wipe-reveal"]
      }
    },
    "additionalProperties": false
  },
  "defaultProps": {
    "alignment": "center",
    "animationPreset": "fade-up"
  },
  "capabilities": {
    "supportsTransparentBackground": true,
    "supportsResponsiveLayout": true
  }
}
```

## 11.4 Timeline schema example

``` json
{
  "schemaVersion": "1.0",
  "composition": {
    "id": "main",
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "durationInFrames": 1800
  },
  "scenes": [
    {
      "id": "scene-01",
      "startFrame": 0,
      "durationInFrames": 210,
      "background": {"type": "color", "value": "#102F60"},
      "layers": [
        {
          "id": "title-01",
          "type": "component",
          "componentKey": "typography.title-reveal",
          "componentVersion": "1.0.0",
          "startFrame": 10,
          "durationInFrames": 160,
          "props": {
            "text": "Masa Depan AI",
            "fontSize": 88,
            "color": "#FFFFFF",
            "alignment": "center",
            "animationPreset": "spring-scale"
          }
        }
      ]
    }
  ]
}
```

## 11.5 Animation preset registry

Each preset defines: - Key and version. - Duration range. -
Easing/spring parameters. - Supported component categories. -
Reduced-motion alternative. - Preview thumbnail/demo. - Props schema. -
Performance profile.

Presets awal: - `fade-in` - `fade-up` - `fade-down` - `spring-scale` -
`slide-left` - `slide-right` - `wipe-reveal` - `mask-reveal` -
`typewriter` - `word-stagger` - `counter-up` - `draw-line` -
`parallax-slow` - `zoom-in` - `zoom-out` - `glitch-light`

## 11.6 Scene timing rules

-   Internal timebase: integer frames.
-   API/editor timebase: milliseconds.
-   Conversion: `frame = round(ms * fps / 1000)` with consistent
    rounding.
-   Timeline duration must be at least the maximum clip end frame.
-   Negative start frames are invalid unless explicitly supported by a
    transition model.
-   Overlap must be intentional and represented.
-   Scene transition duration cannot exceed available neighboring scene
    duration.
-   Audio/video sync uses the same frame/timebase conversion policy.
-   Avoid floating-point drift by converting at compile boundary and
    persisting integer frames.

## 11.7 Composition runtime

Runtime responsibilities: 1. Load validated timeline snapshot. 2.
Resolve component key to local registered React component. 3. Validate
props against component schema. 4. Resolve media asset to short-lived
authorized URL or worker-local file. 5. Calculate sequence placement. 6.
Render scene layers in z-order. 7. Apply transitions and global style
tokens. 8. Render audio/subtitles. 9. Expose composition metadata to
Player and renderer.

------------------------------------------------------------------------

# 12. Voice, Audio, and Subtitle Engineering

## 12.1 TTS provider adapter

Standard internal interface:

``` python
class TTSProvider:
    async def list_voices(self, language: str) -> list: ...
    async def generate(
        self,
        text: str,
        voice_id: str,
        settings: dict,
        output_format: str
    ) -> "AudioResult": ...
```

Provider configuration: - Provider key. - Model/voice ID. - Supported
languages. - Supported formats. - Rate/pitch controls. - SSML support. -
Word timestamp support. - Commercial-use constraints. - Pricing and
limits.

OpenAI TTS dapat menjadi provider awal, tetapi kualitas Bahasa
Indonesia, pronunciation, voice consistency, latency, dan terms harus
dievaluasi sebelum menetapkannya sebagai default produksi. Codex adalah
coding agent, bukan TTS provider. Voice cloning hanya dengan consent dan
hak yang sah.

## 12.2 Audio pipeline

1.  Split narration into stable segments.
2.  Generate segment audio.
3.  Validate MIME, duration, sample rate, and file integrity.
4.  Normalize audio format.
5.  Align segments to script.
6.  Concatenate with configurable pauses.
7.  Mix music and SFX.
8.  Apply ducking under narration.
9.  Loudness/peak validation.
10. Store master and per-scene audio assets.

Preserve per-segment audio so a single script change does not force
regeneration of every unaffected segment.

## 12.3 Audio mixing

-   Narration is primary.
-   Music ducking uses configurable sidechain/envelope.
-   SFX must not obscure speech.
-   Fade-in/out configured in timeline.
-   Peak clipping check.
-   Loudness target configurable by output profile.
-   Final codec and sample rate pinned by render profile.
-   Store original and processed versions separately.

## 12.4 Subtitle pipeline

1.  Use TTS provider timestamps if reliable.
2.  Otherwise use forced alignment service.
3.  Fallback sentence-level alignment only with explicit lower
    precision.
4.  Split captions for readability.
5.  Ensure start \< end and no invalid overlap.
6.  Generate JSON canonical track.
7.  Export SRT/VTT.
8.  Burn-in via Remotion when requested.

Subtitle modes: - Sentence captions. - Word highlight. - Karaoke. -
Minimal lower-third. - Multi-line accessibility captions.

------------------------------------------------------------------------

# 13. Asset Generation and Governance

## 13.1 Asset types

-   User uploads: image, SVG, audio, video, font (restricted).
-   Generated images.
-   Stock media.
-   Icons and vector graphics.
-   3D assets.
-   Fonts.
-   Music and sound effects.
-   Brand logos.

## 13.2 Asset lifecycle

`requested → generating/uploading → validating → available → attached → archived/deleted`

## 13.3 Validation

-   MIME sniffing; do not trust extension.
-   File size limits.
-   Malware scanning where supported.
-   SVG sanitization.
-   Font license metadata.
-   Image dimension limits.
-   Audio/video duration and codec inspection.
-   3D asset format and polygon/resource limits.
-   Ownership and workspace access.
-   SHA-256 checksum.
-   Provenance and license records.

## 13.4 Rights and provenance

Each external/generated asset must track: - Source/provider. - Original
asset reference. - Prompt or retrieval metadata where applicable. -
Creator/owner if known. - License type. - Commercial-use permission. -
Attribution requirements. - Expiry/usage restrictions. - User
confirmation where necessary.

Do not mark an asset commercially cleared unless evidence supports it.

------------------------------------------------------------------------

# 14. Rendering Lifecycle and Infrastructure

## 14.1 Render lifecycle

``` mermaid
stateDiagram-v2
  [*] --> queued
  queued --> preparing
  preparing --> rendering
  rendering --> uploading
  uploading --> validating
  validating --> completed
  preparing --> failed
  rendering --> failed
  uploading --> failed
  validating --> failed
  queued --> cancel_requested
  preparing --> cancel_requested
  rendering --> cancel_requested
  cancel_requested --> cancelled
  failed --> queued: retry
  completed --> [*]
  cancelled --> [*]
```

## 14.2 Render request snapshot

Render job must pin: - Timeline ID/version/hash. - Composition bundle
version. - Component registry versions. - Fonts and asset references. -
Render profile. - FPS/resolution/codec. - Subtitle and audio mix
configuration. - Renderer version. - Dependency lockfile/build
identifier.

## 14.3 Worker execution

1.  Claim job using atomic lease.
2.  Verify job is still eligible.
3.  Load immutable render snapshot.
4.  Resolve assets securely.
5.  Verify all assets and fonts.
6.  Load exact composition bundle.
7.  Validate composition props.
8.  Start Remotion render.
9.  Update progress from actual renderer callbacks.
10. Capture logs and diagnostics.
11. Upload output to private storage.
12. Validate output metadata and playable file.
13. Generate thumbnail and sidecar subtitles.
14. Persist artifact metadata/checksum.
15. Mark completed and emit event.
16. Cleanup temp files.

## 14.4 Render profiles

  Profile    Use                Suggested settings
  ---------- ------------------ ---------------------------
  Preview    Fast draft         720p, lower quality
  Standard   Social delivery    1080p, H.264
  High       Premium delivery   1080p high quality
  Vertical   Short-form         1080×1920
  Square     Feed               1080×1080
  Master     Archive            Configurable high bitrate

Exact codec, CRF, bitrate, and audio parameters must be benchmarked and
versioned; do not promise identical output size across projects.

## 14.5 Concurrency and scaling

-   Set worker concurrency based on CPU/RAM and composition complexity.
-   Use queue priority tiers.
-   Reserve capacity for interactive previews if required.
-   Apply workspace/user quotas.
-   Prevent one tenant from starving others.
-   Autoscale based on queue depth and worker utilization where
    infrastructure supports it.
-   Record render duration, frames/sec, memory peak, CPU time, and
    output size.

## 14.6 Failure taxonomy

-   `ASSET_NOT_FOUND`
-   `ASSET_ACCESS_DENIED`
-   `UNSUPPORTED_MEDIA`
-   `FONT_MISSING`
-   `COMPOSITION_NOT_FOUND`
-   `COMPONENT_VERSION_MISMATCH`
-   `INVALID_COMPONENT_PROPS`
-   `BROWSER_CRASH`
-   `FFMPEG_FAILURE`
-   `WORKER_OOM`-   `RENDER_TIMEOUT`
-   `STORAGE_UPLOAD_FAILED`
-   `OUTPUT_VALIDATION_FAILED`
-   `CANCELLED_BY_USER`

Errors shown to user must be safe and actionable; internal logs may
contain diagnostics but must redact secrets and personal data.

------------------------------------------------------------------------

# 15. Billing, Usage, and Cost Controls

## 15.1 Metered dimensions

-   LLM input/output tokens.
-   TTS characters or audio seconds.
-   Image generation count/resolution.
-   Transcription/alignment minutes.
-   Render frames or render seconds.
-   Storage GB-month.
-   Download/egress where billable.
-   Premium assets or licensed stock.

## 15.2 Cost estimation

Before execution, calculate: - Estimated LLM cost. - Estimated TTS
cost. - Estimated image/media cost. - Estimated render compute. -
Estimated storage. - Platform margin/credit price.

Display estimated range, not false precision. Reconcile with actual
provider usage afterward.

## 15.3 Credit ledger rules

-   Ledger is append-only.
-   Each charge/refund has idempotency key.
-   Reserve credits before paid operation if plan requires.
-   Settle against actual usage.
-   Refund unused reservation.
-   Never allow negative balance unless explicit enterprise policy.
-   Provider cost and customer credit charge are distinct measures.
-   Render retries must not duplicate user charges without policy
    decision.

## 15.4 Plan model

Possible plans: - Free trial. - Creator. - Pro. - Team. - Enterprise.

Plan quotas should be configuration-driven, not hardcoded in frontend.

------------------------------------------------------------------------

# 16. Security, Privacy, and Compliance

## 16.1 Authentication and authorization

-   Supabase Auth.
-   Verify JWT signature, issuer, audience, expiry.
-   Enforce workspace membership and role.
-   Apply tenant scope in every service query.
-   Internal worker authentication via short-lived service
    identity/secret.
-   Admin endpoints require explicit admin role and audit log.

## 16.2 Secrets

-   Provider API keys in server secret manager/environment.
-   Never store provider secrets in client-visible tables.
-   Never expose service role key to browser.
-   Rotate secrets and restrict access.
-   Redact tokens from logs.

## 16.3 Storage

-   Private buckets by default.
-   Signed URLs with short expiry.
-   Validate object ownership before signing.
-   Separate temporary and permanent objects.
-   Prevent path traversal and arbitrary object overwrite.
-   Cleanup abandoned temporary files.
-   Retention and deletion policies.

## 16.4 Upload security

-   MIME sniffing.
-   Size/duration limits.
-   Malware scanning where available.
-   SVG sanitization.
-   Reject executable files.
-   Restrict font and 3D formats.
-   Protect against decompression bombs and malformed media.
-   Process uploads in isolated workers.

## 16.5 LLM security

-   Prompt injection defenses.
-   Tool allowlists.
-   Schema validation.
-   No arbitrary code execution.
-   No secrets in model context.
-   Source content treated as untrusted.
-   PII minimization.
-   Moderation/safety review for supported content categories.

## 16.6 Privacy and deletion

-   User can delete project and request deletion of associated assets.
-   Deletion workflow handles DB rows, storage objects, derived files,
    and caches.
-   Define backup retention and deletion limitations clearly.
-   Audit records retain only necessary metadata.
-   Voice cloning and personal voice data require explicit consent and
    retention rules.
-   Establish terms for user-provided copyrighted materials.

------------------------------------------------------------------------

# 17. Observability and Operations

## 17.1 Required telemetry

-   API latency and error rate.
-   LLM latency, token usage, and provider failures.
-   Agent task duration and retry rate.
-   TTS duration and failure rate.
-   Asset generation time.
-   Queue depth and oldest job age.
-   Worker heartbeat and utilization.
-   Render frames/sec.
-   Render success/failure rate.
-   Storage upload failures.
-   Cost per project and per minute of output.
-   User-visible pipeline completion time.

## 17.2 Correlation

Every request/job must carry: - `request_id` - `workspace_id` -
`project_id` - `production_run_id` - `agent_task_id` - `render_job_id` -
`worker_id`

Avoid logging raw prompts or full voice text by default if not required.
Provide controlled diagnostic logging and redaction.

## 17.3 Alerts

-   Queue backlog exceeds threshold.
-   Render worker offline.
-   Repeated provider failures.
-   Storage capacity/egress threshold.
-   Abnormal cost spike.
-   High job failure rate.
-   Stuck tasks with expired lease.
-   Database connection saturation.
-   Security/auth anomaly.

## 17.4 Operational runbooks

Must provide: - Provider outage handling. - Queue backlog recovery. -
Stuck job recovery. - Worker restart. - Render failure diagnosis. -
Storage cleanup. - Database restore. - Secret rotation. - Billing
reconciliation. - Incident communication.

------------------------------------------------------------------------

# 18. Testing and Quality Strategy

Testing must validate real contracts and behavior; avoid meaningless
repeated tests or tests that merely assert mocks.

## 18.1 Test layers

### Unit tests

-   Prompt normalization.
-   Schema validators.
-   Timeline frame calculations.
-   Duration estimation.
-   Subtitle timing.
-   Component prop validators.
-   Billing calculations.
-   Authorization helpers.

### Integration tests

-   FastAPI + Supabase.
-   RLS/tenant isolation.
-   Queue enqueue/consume.
-   LLM provider adapter contract.
-   TTS adapter contract.
-   Storage upload/download signing.
-   Render worker input contract.
-   Webhook verification.

### Composition tests

-   Each registered component renders a deterministic sample.
-   Snapshot/reference frames for key components.
-   Font and asset resolution.
-   Aspect ratio behavior.
-   No overflow beyond safe area.
-   Reduced-motion mode.

### End-to-end tests

-   Prompt → brief → script → storyboard.
-   Script/storyboard edit and version creation.
-   Voice and subtitle generation.
-   Timeline compile and preview.
-   Render request → worker → MP4 artifact.
-   Download authorization.
-   Cancellation and retry.
-   Tenant boundary and unauthorized access.

### Load tests

-   Concurrent generation requests.
-   Queue saturation.
-   Render concurrency.
-   Storage upload throughput.
-   API rate limiting.
-   Workspace fairness.

## 18.2 Production acceptance criteria

MVP is accepted only when:

1.  User can authenticate and create workspace/project.
2.  User can submit a real prompt and receive a persisted creative
    brief.
3.  Script and storyboard are generated through configured provider(s),
    not mock output.
4.  Structured outputs pass schema validation.
5.  User can edit and version script/storyboard.
6.  Voice generation produces a real playable audio artifact.
7.  Subtitle timing is derived from actual audio alignment or clearly
    labeled fallback precision.
8.  Timeline compiler produces valid immutable timeline.
9.  Preview and render use the same composition bundle.
10. Remotion worker creates a playable MP4.
11. Render status/progress comes from actual worker state.
12. Render artifact is stored privately and downloadable through
    authorization.
13. User cannot access another workspace's data.
14. Duplicate requests do not duplicate paid jobs/charges.
15. Cancellation/retry/recovery are functional.
16. Cost/usage is recorded.
17. Failed jobs show actionable errors and preserve diagnostic evidence.
18. No production path silently substitutes mock data or fake success.

------------------------------------------------------------------------

# 19. Engineering Execution Plan

## Phase 0 --- Repository and foundation

Deliverables: - Monorepo structure. - Environment configuration. -
Shared contracts package. - CI checks and migration workflow. - Local
development environment. - Architecture decision records. - Secure
secrets handling.

Exit criteria: - All apps/services build. - API health check works. -
Database migrations run from clean state. - Shared contracts compile in
Python/TypeScript boundaries.

## Phase 1 --- Identity, workspace, and project

Deliverables: - Supabase Auth integration. -
Profiles/workspaces/memberships. - RBAC and RLS. - Project CRUD. -
Customer dashboard shell. - Admin shell. - Audit log.

Exit criteria: - Tenant isolation tests pass. - Role permissions
verified. - Project CRUD uses FastAPI business endpoints.

## Phase 2 --- AI Gateway and orchestration

Deliverables: - Provider adapter interface. - Model registry. - Prompt
registry/versioning. - Production run and task lifecycle. - Redis
queue. - Checkpoints, retries, idempotency. - Usage capture.

Exit criteria: - One real LLM task can execute, persist structured
output, record usage, and recover after worker interruption.

## Phase 3 --- Creative intelligence

Deliverables: - Prompt Interpreter. - Research/evidence structuring
(source-limited MVP). - Scriptwriter. - Story Director. - Storyboard
Agent. - Human approval gates. - Versioned artifacts and editors.

Exit criteria: - A real prompt produces editable brief, script, and
scene storyboard with traceable prompt/model versions.

## Phase 4 --- Asset, voice, and subtitle

Deliverables: - Asset registry and upload flow. - Asset validation and
provenance. - TTS adapter. - Voice generation. - Audio processing. -
Alignment. - Subtitle generation/editor. - SRT/VTT export.

Exit criteria: - One complete narration track and synchronized subtitle
track exist as persisted assets.

## Phase 5 --- Timeline and motion component system

Deliverables: - Timeline schema. - Deterministic compiler. - Component
registry. - Animation preset registry. - Composition templates. -
Preview using Remotion Player. - Scene editor.

Exit criteria: - Approved storyboard and assets compile to a valid
timeline; preview reflects exact timeline snapshot.

## Phase 6 --- Remotion render infrastructure

Deliverables: - Dedicated Node.js render worker. - Queue integration. -
Worker leases and cancellation. - Render profiles. - Progress events. -
MP4 and thumbnail. - Output validation. - Render diagnostics.

Exit criteria: - Real MP4 rendered from a persisted timeline, stored
securely, and downloadable by authorized user.

## Phase 7 --- Product completion

Deliverables: - Project workspace complete. - Scene regeneration. -
Brand kit. - Usage and billing. - Cost estimate. - Admin controls. -
Notifications. - Error and recovery UX.

Exit criteria: - Full customer journey works without manual database
intervention.

## Phase 8 --- Production hardening

Deliverables: - Security review. - Load and failure tests. -
Backup/restore drill. - Observability and alerts. - Provider outage
runbooks. - Cost guardrails. - License review. - Production deployment
checklist.

Exit criteria: - All critical acceptance criteria pass with evidence;
unresolved blockers are documented and release is blocked where
necessary.

------------------------------------------------------------------------

# 20. Definition of Done (DoD)

A feature is not complete merely because code exists.

It is complete only when: - Frontend UI is connected to actual API. -
API uses real database/provider/worker behavior. - Authorization and RLS
are verified. - Input/output contracts are typed and validated. -
Loading, empty, success, and error states exist. - Async job state
persists and recovers. - Logs and correlation IDs exist. - Tests cover
meaningful behavior. - Documentation/runbook is updated. - No fake/mock
data exists in production path. - No secret is exposed. - Versioning and
audit requirements are met. - Acceptance evidence is attached to the
implementation record.

## 20.1 Release blockers

-   Cross-tenant data exposure.
-   Arbitrary code execution through timeline or composition props.
-   Service-role/provider secrets exposed.
-   Paid operations without quota/usage controls.
-   Render marked complete without valid output artifact.
-   Broken cancellation causing unbounded compute.
-   Missing asset rights metadata for commercial stock assets.
-   Database migrations destructive without recovery plan.
-   No operational access to diagnose stuck production jobs.

------------------------------------------------------------------------

# 21. Decisions and Open Questions

The architecture can proceed with safe defaults, but the following
decisions should be confirmed before commercial launch:

  -------------------------------------------------------------------------
  Topic                   Recommended default       Decision needed
  ----------------------- ------------------------- -----------------------
  Product name            MotionForge AI (working   Final brand
                          title)                    

  Initial language        Indonesian +              Launch languages
                          English-ready             

  Primary format          16:9 and 9:16             Launch formats

  Default TTS             OpenAI TTS adapter        Benchmark Indonesian
                                                    voices

  LLM                     OpenAI first,             Models and cost
                          adapter-based             ceilings

  Image provider          Provider adapter          Provider/license

  Music                   Licensed library          Catalog and terms

  Render hosting          Dedicated container       Provider and capacity
                          workers                   

  Billing                 Credits + subscription    Pricing and margin

  Approval                Review at                 Default automation
                          brief/script/storyboard   level

  Storage retention       Configurable by plan      Retention period

  Remotion license        Verify current applicable Company/automation
                          license                   license
  -------------------------------------------------------------------------

## 21.1 Recommended defaults for first implementation

Agar engineering tidak tertahan oleh keputusan minor: - Gunakan nama
kerja MotionForge AI. - Mulai dengan Bahasa Indonesia dan English-ready
schema. - Mulai dengan 16:9 dan 9:16. - Default 1080p, 30 FPS. - Gunakan
OpenAI adapter untuk LLM dan evaluasi TTS Bahasa Indonesia secara
nyata. - Gunakan template dan component registry internal. - Gunakan
approval gate setelah brief, script, dan storyboard. - Gunakan private
storage. - Gunakan dedicated render worker. - Jangan aktifkan public
template marketplace pada MVP. - Jangan jalankan arbitrary user code.

------------------------------------------------------------------------

# 22. Engineering Handoff Checklist

Sebelum coding: - \[ \] Repository dan branch utama ditetapkan. - \[ \]
Environment dan deployment target dipilih. - \[ \] Supabase project
ditetapkan. - \[ \] Remotion licensing path diverifikasi. - \[ \]
Provider API credentials disiapkan melalui secret manager. - \[ \]
Schema contracts disepakati. - \[ \] Database migration baseline
dibuat. - \[ \] Architecture decision records dibuat.

Saat implementasi: - \[ \] Implementasi berdasarkan phase dan
dependency. - \[ \] Tidak membuat tabel/endpoint duplikat. - \[ \] Tidak
mengganti arsitektur tanpa ADR. - \[ \] Tidak mengubah UI yang telah
disetujui tanpa kebutuhan. - \[ \] Tidak menggunakan mock data pada
production path. - \[ \] Tidak menandai phase complete tanpa evidence. -
\[ \] Tidak deploy production sebelum release gate.

Sebelum release: - \[ \] Full customer journey terverifikasi. - \[ \]
Tenant isolation terverifikasi. - \[ \] Real provider generation
terverifikasi. - \[ \] Real Remotion MP4 render terverifikasi. - \[ \]
Download authorization terverifikasi. - \[ \] Billing/usage
reconciliation terverifikasi. - \[ \] Cancellation/retry/recovery
terverifikasi. - \[ \] Monitoring, alerts, dan runbooks tersedia. - \[
\] Backup/restore dan rollback plan tersedia. - \[ \] License dan rights
review selesai.

------------------------------------------------------------------------

# Appendix A --- Canonical JSON contracts

## A.1 Scene contract

``` json
{
  "id": "scene-uuid",
  "index": 0,
  "title": "Opening Hook",
  "purpose": "Capture attention",
  "narration": {
    "segment_ids": ["segment-01"],
    "text": "Pernahkah Anda membayangkan..."
  },
  "timing": {
    "estimated_duration_ms": 7000,
    "start_frame": 0,
    "duration_frames": 210
  },
  "visual": {
    "description": "Abstract technology network",
    "layout_key": "hero-centered",
    "background": {"type": "color", "value": "#102F60"},
    "component_keys": ["typography.title-reveal"],
    "asset_ids": []
  },
  "motion": {
    "entry": "fade-up",
    "exit": "fade",
    "transition_out": "wipe"
  },
  "qa": {
    "status": "pending",
    "findings": []
  }
}
```

## A.2 Voice profile contract

``` json
{
  "id": "voice-profile-uuid",
  "provider_key": "openai",
  "voice_key": "configured-voice",
  "language": "id-ID",
  "tone": "professional",
  "pace": "medium",
  "pronunciation_dictionary": [],
  "consent_reference": null
}
```

## A.3 Render config contract

``` json
{
  "profile": "standard",
  "format": "mp4",
  "codec": "h264",
  "width": 1920,
  "height": 1080,
  "fps": 30,
  "audio_codec": "aac",
  "burn_subtitles": true,
  "thumbnail": true,
  "timeline_hash": "sha256:...",
  "composition_version": "1.0.0"
}
```

------------------------------------------------------------------------

# Appendix B --- Glossary

  Term                 Definition
  -------------------- ----------------------------------------------------
  Agent                Komponen AI dengan tanggung jawab spesifik
  Artifact             Output produksi berversi
  Brief                Ringkasan kebutuhan dan tujuan video
  Story arc            Struktur narasi
  Storyboard           Rencana visual per scene
  Scene                Unit narasi dan visual
  Timeline             Susunan clip/layer berbasis frame
  Composition          React/Remotion composition yang dirender
  Component registry   Daftar komponen animasi yang diizinkan
  Preset               Parameter animasi terstandar
  TTS                  Text-to-Speech
  Alignment            Penentuan timestamp audio terhadap teks
  Render worker        Proses Node.js yang menjalankan Remotion render
  Checkpoint           Bukti state yang memungkinkan workflow dilanjutkan
  Idempotency          Operasi berulang tidak menghasilkan duplikasi efek
  RLS                  Row Level Security
  Tenant               Workspace/organisasi pengguna

------------------------------------------------------------------------

# Appendix C --- External technical references

Gunakan dokumentasi resmi dan verifikasi ulang versi, harga, dan lisensi
saat implementasi:

-   Remotion documentation: https://www.remotion.dev/docs
-   Remotion Player: https://www.remotion.dev/docs/player
-   Remotion Renderer: https://www.remotion.dev/docs/renderer
-   Remotion licensing: https://www.remotion.dev/license
-   Supabase documentation: https://supabase.com/docs
-   Supabase Row Level Security:
    https://supabase.com/docs/guides/database/postgres/row-level-security
-   Supabase Storage: https://supabase.com/docs/guides/storage
-   FastAPI documentation: https://fastapi.tiangolo.com/
-   OpenAI API documentation: https://platform.openai.com/docs
-   OpenAI Text-to-Speech:
    https://platform.openai.com/docs/guides/text-to-speech
-   FFmpeg documentation: https://ffmpeg.org/documentation.html
-   PostgreSQL documentation: https://www.postgresql.org/docs/

**Peringatan:** API, model, provider capability, pricing, dependency
compatibility, dan lisensi dapat berubah. Engineering wajib
memverifikasi dokumentasi dan terms terkini sebelum mengunci versi
produksi.

------------------------------------------------------------------------

**END OF MASTER PRD & MASTER ENGINEERING EXECUTION SPECIFICATION**