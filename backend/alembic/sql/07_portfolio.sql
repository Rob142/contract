-- 기능 4: 포트폴리오 (docs/기획서_반영_TODO.md PF-01~07)

CREATE TABLE portfolio_items (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id              uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id            uuid NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
  title                 text NOT NULL,
  description           text,
  job_type              text NOT NULL CHECK (job_type IN ('dev', 'design', 'video', 'marketing')),
  period_start          date,
  period_end            date,
  cover_attachment_id   uuid REFERENCES attachments(id) ON DELETE SET NULL,
  status                text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'ready', 'archived')),
  visibility            text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'link', 'public')),
  share_slug            text UNIQUE,
  show_client_name      boolean NOT NULL DEFAULT false,
  feedback_consent_at   timestamptz,       -- 클라이언트에게 공개 동의를 받았다고 프리랜서가 확인한 시각
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CHECK (period_start IS NULL OR period_end IS NULL OR period_end >= period_start),
  CHECK (visibility = 'private' OR share_slug IS NOT NULL)
);
CREATE INDEX portfolio_items_owner_idx ON portfolio_items (owner_id, status);

CREATE TABLE portfolio_assets (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id        uuid NOT NULL REFERENCES portfolio_items(id) ON DELETE CASCADE,
  attachment_id  uuid NOT NULL REFERENCES attachments(id) ON DELETE CASCADE,
  position       integer NOT NULL DEFAULT 0,
  UNIQUE (item_id, attachment_id)
);

CREATE TABLE portfolio_quotes (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id      uuid NOT NULL REFERENCES portfolio_items(id) ON DELETE CASCADE,
  feedback_id  uuid NOT NULL REFERENCES task_feedback(id) ON DELETE CASCADE,
  quote        text NOT NULL CHECK (length(quote) BETWEEN 1 AND 500),
  anonymize    boolean NOT NULL DEFAULT true,
  UNIQUE (item_id, feedback_id)
);

CREATE TRIGGER portfolio_items_set_updated_at BEFORE UPDATE ON portfolio_items
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
