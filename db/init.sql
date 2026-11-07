-- Production schema (PostgreSQL 16). The dev gateway stores bundles as JSON files instead.
CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector: similar-question and similar-doubt search
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  phone        text UNIQUE NOT NULL,
  language     text NOT NULL DEFAULT 'hinglish',
  plan         text NOT NULL DEFAULT 'free',
  created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE exams  (id serial PRIMARY KEY, name text NOT NULL, year int, shift text);
CREATE TABLE topics (id serial PRIMARY KEY, name text NOT NULL, subject text NOT NULL, parent_id int REFERENCES topics(id));

-- The YAML library is the source of truth; this table mirrors it for joins and analytics.
CREATE TABLE tricks (
  id            text PRIMARY KEY,                 -- e.g. alg-identity-a4-a2b2-b4
  name          text NOT NULL,
  subject       text NOT NULL,
  topic         text NOT NULL,
  speed_seconds int  NOT NULL,
  yaml_sha      text NOT NULL
);

CREATE TABLE questions (
  id             text PRIMARY KEY,
  exam_id        int REFERENCES exams(id),
  topic_id       int REFERENCES topics(id),
  subject        text,
  text_md        text NOT NULL,
  options        jsonb NOT NULL DEFAULT '[]',
  correct_option text,
  difficulty     smallint,
  image_url      text,
  embedding      vector(1024),
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX questions_embedding_idx ON questions USING hnsw (embedding vector_cosine_ops);

CREATE TABLE lessons (
  id                bigserial PRIMARY KEY,
  question_id       text NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  trick_id          text NOT NULL,
  language          text NOT NULL,
  script            jsonb NOT NULL,               -- the LessonScript (see schema/lesson_script.schema.json)
  verified          boolean NOT NULL DEFAULT false,
  verify_log        jsonb,
  estimated_seconds int,
  review_status     text NOT NULL DEFAULT 'auto', -- auto | approved | rejected
  version           int NOT NULL DEFAULT 1,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (question_id, trick_id, language, version)
);

CREATE TABLE doubts (
  id            bigserial PRIMARY KEY,
  user_id       uuid REFERENCES users(id),
  lesson_id     bigint REFERENCES lessons(id) ON DELETE CASCADE,
  step_id       text NOT NULL,
  text          text NOT NULL,
  language      text NOT NULL,
  answer_script jsonb,
  verified      boolean NOT NULL DEFAULT false,
  embedding     vector(1024),
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX doubts_embedding_idx ON doubts USING hnsw (embedding vector_cosine_ops);

CREATE TABLE attempts (
  id          bigserial PRIMARY KEY,
  user_id     uuid NOT NULL REFERENCES users(id),
  question_id text NOT NULL REFERENCES questions(id),
  chosen      text, correct boolean, time_ms int, trick_used text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE progress (
  user_id uuid NOT NULL REFERENCES users(id),
  lesson_id bigint NOT NULL REFERENCES lessons(id),
  watched_pct real NOT NULL DEFAULT 0, saved boolean NOT NULL DEFAULT false,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, lesson_id)
);

CREATE TABLE reviews (
  id bigserial PRIMARY KEY, lesson_id bigint NOT NULL REFERENCES lessons(id),
  reviewer text NOT NULL, status text NOT NULL, notes text, created_at timestamptz NOT NULL DEFAULT now()
);
