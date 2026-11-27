-- face-swap schema (Postgres 13+). All times UTC timestamptz.
-- Access rule: every query goes through the data layer's owner check (no RLS).
-- Only the owner's own face, captured by camera with a liveness check, can be used.

create extension if not exists pgcrypto;

create table users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  password_hash text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- one face per user, camera capture + liveness only
create table faces (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references users(id) on delete cascade,
  source text not null default 'camera' check (source = 'camera'),
  image_key text not null,
  embedding bytea,
  liveness_challenge_id text not null unique,
  liveness_passed_at timestamptz not null,
  age_check_passed boolean not null check (age_check_passed),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table source_videos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  kind text not null check (kind in ('template','upload')),
  video_key text not null,
  bytes bigint not null check (bytes > 0),
  duration_s numeric(7,2) check (duration_s > 0),
  aspect text check (aspect in ('9:16','16:9','other')),
  rights_confirmed boolean not null check (rights_confirmed),
  rights_note text,
  detected_faces jsonb not null default '[]',
  analysis_status text not null default 'pending'
    check (analysis_status in ('pending','analyzing','done','failed')),
  safety_status text not null default 'pending'
    check (safety_status in ('pending','passed','blocked')),
  safety_result jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on source_videos (user_id, created_at desc);
create index on source_videos (analysis_status);

create table templates (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  source_video_id uuid not null unique references source_videos(id) on delete cascade,
  title text not null,
  category text,
  license_note text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on templates (user_id, category);

create table swap_jobs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  source_video_id uuid not null references source_videos(id) on delete cascade,
  face_id uuid references faces(id) on delete set null,
  target_face_index integer not null check (target_face_index >= 0),
  aspect text not null check (aspect in ('9:16','16:9')),
  idempotency_key text not null,
  provider text not null,
  provider_task_id text,
  safety_status text not null default 'pending'
    check (safety_status in ('pending','passed','blocked')),
  status text not null default 'queued'
    check (status in ('queued','submitted','processing','postprocessing','done','failed','blocked','cancelled')),
  -- nothing goes to the provider unless safety passed
  constraint safety_before_submit check (
    status in ('queued','failed','blocked','cancelled') or safety_status = 'passed'
  ),
  -- a job can only be submitted while a face exists
  constraint face_required_to_run check (
    status in ('queued','done','failed','blocked','cancelled') or face_id is not null
  ),
  attempts integer not null default 0,
  error text,
  estimated_seconds numeric(7,2),
  locked_at timestamptz,
  next_poll_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, idempotency_key),
  unique (provider, provider_task_id)
);
create index on swap_jobs (status, next_poll_at);
create index on swap_jobs (user_id, created_at desc);
create index on swap_jobs (source_video_id);
create index on swap_jobs (face_id);

create table outputs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  job_id uuid not null unique references swap_jobs(id) on delete cascade,
  video_key text not null,
  aspect text not null check (aspect in ('9:16','16:9')),
  height integer not null check (height >= 720),
  -- AI labeling cannot be turned off
  watermarked boolean not null check (watermarked),
  c2pa_signed boolean not null check (c2pa_signed),
  c2pa_manifest_key text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on outputs (user_id, created_at desc);

create table usage_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  job_id uuid references swap_jobs(id) on delete set null,
  service text not null check (service in ('faceswap','claude','storage')),
  units numeric not null,
  unit text not null,              -- seconds, tokens_in, tokens_out, bytes
  cost_micro_usd bigint not null default 0 check (cost_micro_usd >= 0),
  currency text not null default 'USD',
  created_at timestamptz not null default now()
);
create index on usage_events (user_id, created_at);
create index on usage_events (job_id);
