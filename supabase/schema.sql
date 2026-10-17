create extension if not exists pgcrypto;

create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null default 'Reader',
  edition_lang text not null default 'en'
    check (edition_lang in ('en','ur','ar','hi','bn','es','fr','zh')),
  source_langs text[] not null default '{}',          -- extra languages to fetch from
  city text,
  timezone text not null default 'UTC',               -- IANA name from the browser
  reading_minutes int not null default 10 check (reading_minutes in (5,10,20)),
  text_size text not null default 'M' check (text_size in ('S','M','L','XL')),
  theme text not null default 'auto' check (theme in ('day','night','auto')),
  notify boolean not null default false,              -- morning push (F-21)
  delivery_time time not null default '06:00',
  onboarded_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.interests (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  label text not null check (char_length(label) <= 60),   -- shown to the user
  topic_key text,                                         -- from topics.json, null for custom/learned
  query text not null check (char_length(query) <= 200),  -- Google News search query
  weight real not null default 0.5 check (weight between 0.05 and 1.0),
  source text not null default 'onboarding' check (source in ('onboarding','custom','learned')),
  active boolean not null default true,
  low_since timestamptz,                                  -- set when weight < 0.1
  created_at timestamptz not null default now(),
  unique (user_id, label)
);
create index interests_user_idx on public.interests (user_id) where active;

create table public.interest_history (
  id bigserial primary key,
  interest_id uuid not null references public.interests(id) on delete cascade,
  old_weight real not null,
  new_weight real not null,
  reason text not null,            -- 'click','more_like','less_like','dwell','ignored','taste_test','learner','manual'
  created_at timestamptz not null default now()
);
create index interest_history_idx on public.interest_history (interest_id, created_at);

create table public.blocked_sources (
  user_id uuid not null references auth.users(id) on delete cascade,
  source_name text not null,
  created_at timestamptz not null default now(),
  primary key (user_id, source_name)
);

create table public.articles (
  id uuid primary key default gen_random_uuid(),
  url text not null,
  url_hash text not null unique,                  -- sha256 of normalized url
  title text not null,
  source_name text,
  summary text,                                   -- feed summary, HTML stripped, ≤ 600 chars
  image_url text,
  lang text,
  published_at timestamptz,
  fetched_at timestamptz not null default now()
);
create index articles_published_idx on public.articles (published_at desc);

create table public.editions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  edition_date date not null,                     -- reader's local date
  version int not null default 1,
  edition_no int not null,                        -- 1, 2, 3 … per user
  lang text not null,
  status text not null default 'generating'
    check (status in ('generating','ready','failed','superseded')),
  lead_headline text,
  lead_dek text,
  editor_note text,
  three_things jsonb not null default '[]',       -- ["…","…","…"]
  section_order text[] not null default '{}',
  pdf_path text,                                  -- storage path in bucket 'papers'
  used_fallback boolean not null default false,
  generation_ms int,
  sources_count int,                              -- feeds fetched successfully (freshness line)
  ready_at timestamptz,                           -- "Printed at 06:02"
  notified_at timestamptz,                        -- morning push sent (F-21)
  created_at timestamptz not null default now(),
  unique (user_id, edition_date, version)
);
create index editions_user_date_idx on public.editions (user_id, edition_date desc);

create table public.edition_articles (
  id uuid primary key default gen_random_uuid(),
  edition_id uuid not null references public.editions(id) on delete cascade,
  article_id uuid not null references public.articles(id),
  section text not null,                          -- section key, e.g. 'technology', 'your_city', 'world'
  slot text not null check (slot in ('lead','secondary','brief')),
  position int not null,                          -- order within the edition
  headline text not null,                         -- in edition language
  summary text not null,                          -- in edition language
  why text,                                       -- "Because you follow AI startups"
  topic_key text,
  interest_id uuid references public.interests(id) on delete set null,
  unique (edition_id, article_id)
);
create index edition_articles_edition_idx on public.edition_articles (edition_id, position);

-- translated copies of an edition (language switch, F-12)
create table public.edition_translations (
  edition_id uuid not null references public.editions(id) on delete cascade,
  lang text not null,
  payload jsonb not null,           -- {lead_headline, lead_dek, editor_note, three_things, articles:[{id, headline, summary, why}]}
  created_at timestamptz not null default now(),
  primary key (edition_id, lang)
);

create table public.signals (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  edition_article_id uuid references public.edition_articles(id) on delete set null,
  kind text not null check (kind in ('open','click','more_like','less_like','skip_source','dwell','impression_no_click','pdf','taste_up','taste_down','save','puzzle_correct')),
  value real,                                     -- dwell seconds, etc.
  processed_by_learner boolean not null default false,
  created_at timestamptz not null default now()
);
create index signals_user_idx on public.signals (user_id, created_at desc);
create index signals_read_idx on public.signals (edition_article_id) where kind in ('open','click');  -- mark as read (F-22)

create table public.suggestions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  label text not null,
  query text not null,
  reason text,
  status text not null default 'pending' check (status in ('pending','accepted','rejected')),
  created_at timestamptz not null default now(),
  unique (user_id, label)
);

create table public.learner_notes (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  note text not null,               -- in edition language
  created_at timestamptz not null default now()
);

create table public.agent_activity (
  id bigserial primary key,
  edition_id uuid references public.editions(id) on delete cascade,
  user_id uuid references auth.users(id) on delete cascade,
  agent text not null check (agent in ('pipeline','profiler','curator','editor','learner','pdf')),
  kind text not null check (kind in ('started','decision','fallback','error','finished','stat')),
  message text not null check (char_length(message) <= 300),
  data jsonb not null default '{}',
  created_at timestamptz not null default now()
);
create index agent_activity_edition_idx on public.agent_activity (edition_id, created_at);

-- F-23 favorite sources
create table public.favorite_sources (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  catalog_key text,                         -- key in app/data/sources.json, null for custom
  name text not null check (char_length(name) <= 60),
  feed_url text not null check (feed_url ~ '^https?://'),
  kind text not null check (kind in ('catalog','custom')),
  created_at timestamptz not null default now(),
  unique (user_id, feed_url)
);

-- F-18 muted keywords
create table public.muted_keywords (
  user_id uuid not null references auth.users(id) on delete cascade,
  keyword text not null check (char_length(keyword) between 2 and 40),   -- stored lower-case
  created_at timestamptz not null default now(),
  primary key (user_id, keyword)
);

-- F-19 save for later
create table public.saved_articles (
  user_id uuid not null references auth.users(id) on delete cascade,
  edition_article_id uuid not null references public.edition_articles(id) on delete cascade,
  article_id uuid not null references public.articles(id),
  created_at timestamptz not null default now(),
  primary key (user_id, edition_article_id)
);

-- F-21 web push
create table public.push_subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  created_at timestamptz not null default now()
);

-- F-17 headline puzzle
create table public.puzzles (
  edition_id uuid primary key references public.editions(id) on delete cascade,
  items jsonb not null,   -- [{"edition_article_id","masked_headline","answer","choices":[4 strings]}] × 5
  created_at timestamptz not null default now()
);
create table public.puzzle_attempts (
  user_id uuid not null references auth.users(id) on delete cascade,
  edition_id uuid not null references public.editions(id) on delete cascade,
  answers jsonb not null default '[]',   -- [{"q":0,"choice":"beat","correct":true}]
  score int not null default 0,
  completed_at timestamptz,
  primary key (user_id, edition_id)
);

-- safety net: deny all direct client access
alter table public.profiles enable row level security;
alter table public.interests enable row level security;
alter table public.interest_history enable row level security;
alter table public.blocked_sources enable row level security;
alter table public.articles enable row level security;
alter table public.editions enable row level security;
alter table public.edition_articles enable row level security;
alter table public.edition_translations enable row level security;
alter table public.signals enable row level security;
alter table public.suggestions enable row level security;
alter table public.learner_notes enable row level security;
alter table public.agent_activity enable row level security;
alter table public.favorite_sources enable row level security;
alter table public.muted_keywords enable row level security;
alter table public.saved_articles enable row level security;
alter table public.push_subscriptions enable row level security;
alter table public.puzzles enable row level security;
alter table public.puzzle_attempts enable row level security;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('papers', 'papers', false, 20971520, array['application/pdf'])
on conflict (id) do nothing;
