-- music-agent schema (Postgres 13+). All times UTC timestamptz.
-- Access rule: every query goes through the data layer's owner check (no RLS).

create extension if not exists pgcrypto;

create table users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  password_hash text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  title text not null default '無題',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on projects (user_id, updated_at desc);

create table messages (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  role text not null check (role in ('user','assistant','tool','system_note')),
  -- full API content blocks (text, tool_use, tool_result, thinking) kept verbatim
  content jsonb not null,
  seq integer not null,
  created_at timestamptz not null default now(),
  unique (project_id, seq)
);
create index on messages (project_id, seq);

create table attachments (
  id uuid primary key default gen_random_uuid(),
  message_id uuid not null references messages(id) on delete cascade,
  kind text not null check (kind in ('audio','video','image')),
  storage_key text not null,
  bytes bigint not null check (bytes > 0),
  created_at timestamptz not null default now()
);
create index on attachments (message_id);

create table song_specs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  version integer not null,
  title text not null,
  lyrics text,
  style_prompt text not null,
  genre text,
  mood text,
  bpm integer check (bpm between 30 and 300),
  vocal boolean not null default true,
  duration_s integer check (duration_s between 10 and 600),
  source text not null default 'agent' check (source in ('agent','manual')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (project_id, version)
);
create index on song_specs (project_id, version desc);

create table generation_jobs (
  id uuid primary key default gen_random_uuid(),
  spec_id uuid not null references song_specs(id) on delete cascade,
  kind text not null default 'song' check (kind in ('song','stems')),
  provider text not null,
  provider_model text,
  provider_task_id text,
  idempotency_key text not null,
  status text not null default 'queued'
    check (status in ('queued','submitted','generating','done','failed','cancelled')),
  attempts integer not null default 0,
  error text,
  locked_at timestamptz,
  next_poll_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (spec_id, idempotency_key),
  unique (provider, provider_task_id)
);
create index on generation_jobs (status, next_poll_at);
create index on generation_jobs (spec_id);

create table tracks (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  spec_id uuid not null references song_specs(id) on delete cascade,
  job_id uuid not null unique references generation_jobs(id) on delete cascade,
  version integer not null,
  storage_key_mp3 text,
  storage_key_wav text,
  duration_s numeric(7,2),
  provider text not null,
  provider_model text,
  -- which API and which of its terms applied when this was generated
  plan_at_generation text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index on tracks (project_id, created_at desc);
create index on tracks (spec_id);

create table stems (
  id uuid primary key default gen_random_uuid(),
  track_id uuid not null references tracks(id) on delete cascade,
  kind text not null check (kind in ('vocals','drums','bass','other','instrumental')),
  storage_key text not null,
  created_at timestamptz not null default now(),
  unique (track_id, kind)
);

create table usage_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  project_id uuid references projects(id) on delete set null,
  job_id uuid references generation_jobs(id) on delete set null,
  service text not null check (service in ('claude','music','stems','storage')),
  units numeric not null,
  unit text not null,              -- tokens_in, tokens_out, songs, minutes, bytes
  cost_micro_usd bigint not null default 0 check (cost_micro_usd >= 0),
  currency text not null default 'USD',
  created_at timestamptz not null default now()
);
create index on usage_events (user_id, created_at);
create index on usage_events (project_id);
create index on usage_events (job_id);
