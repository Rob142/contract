-- 기능 2·3: 진행 현황 공유, 첨부·증빙, 수정 요청 카운터 (docs/기획서_반영_TODO.md)

-- 템플릿에서 만든 단계를 구분한다
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_source_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_source_check
  CHECK (source IN ('contract', 'estimated', 'manual', 'template'));

-- 계약에서 넘어온 포함 수정 횟수. NULL이면 카운터를 쓰지 않는다
ALTER TABLE projects ADD COLUMN included_revisions integer
  CHECK (included_revisions IS NULL OR included_revisions >= 0);

-- 첨부: 0001에서 만든 attachments(파일 전용)를 결과물·증빙·외부 링크까지 쓰도록 넓힌다.
-- 파일 또는 외부 링크 중 정확히 하나
ALTER TABLE attachments
  ADD COLUMN owner_id    uuid REFERENCES users(id) ON DELETE CASCADE,
  ADD COLUMN invoice_id  uuid REFERENCES invoices(id) ON DELETE SET NULL,
  ADD COLUMN kind        text NOT NULL DEFAULT 'other'
                         CHECK (kind IN ('deliverable', 'evidence', 'other')),
  ADD COLUMN doc_type    text CHECK (doc_type IN ('tax_invoice', 'cash_receipt', 'receipt', 'contract_copy', 'other')),
  ADD COLUMN title       text NOT NULL DEFAULT '',
  ADD COLUMN url         text,
  ADD COLUMN issued_on   date,
  ADD COLUMN amount      numeric(14, 0) CHECK (amount IS NULL OR amount >= 0),
  ADD COLUMN memo        text,
  ADD COLUMN updated_at  timestamptz NOT NULL DEFAULT now();
UPDATE attachments a SET owner_id = p.owner_id FROM projects p WHERE p.id = a.project_id;
UPDATE attachments a SET title = f.original_name FROM files f WHERE f.id = a.file_id;
ALTER TABLE attachments ALTER COLUMN owner_id SET NOT NULL;
ALTER TABLE attachments ALTER COLUMN title DROP DEFAULT;
ALTER TABLE attachments ALTER COLUMN file_id DROP NOT NULL;
-- 단계가 지워져도 첨부(프로젝트 자료)는 남긴다
ALTER TABLE attachments DROP CONSTRAINT IF EXISTS attachments_task_id_fkey;
ALTER TABLE attachments ADD CONSTRAINT attachments_task_id_fkey
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL;
ALTER TABLE attachments ADD CONSTRAINT attachments_file_or_url CHECK ((file_id IS NULL) <> (url IS NULL));
DROP INDEX IF EXISTS attachments_project_idx;
CREATE INDEX attachments_project_idx ON attachments (project_id, kind, created_at DESC);
CREATE INDEX attachments_owner_idx ON attachments (owner_id);

-- 공유 링크: 토큰 원문은 저장하지 않는다
CREATE TABLE share_links (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id      uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  token_hash      text NOT NULL UNIQUE,
  expires_at      timestamptz,                       -- NULL = 만료 없음
  revoked_at      timestamptz,
  show_invoices   boolean NOT NULL DEFAULT false,
  allow_feedback  boolean NOT NULL DEFAULT true,
  last_viewed_at  timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
-- 프로젝트당 유효한 링크는 하나
CREATE UNIQUE INDEX share_links_active_idx ON share_links (project_id) WHERE revoked_at IS NULL;

-- 단계별 피드백: 추가만 가능하다(수정 불가)
CREATE TABLE task_feedback (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id   uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  task_id      uuid NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  author_role  text NOT NULL CHECK (author_role IN ('freelancer', 'client')),
  author_name  text NOT NULL,
  body         text NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX task_feedback_task_idx ON task_feedback (task_id, created_at);

CREATE OR REPLACE FUNCTION forbid_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% rows are append-only', TG_TABLE_NAME USING ERRCODE = 'check_violation';
END;
$$;
CREATE TRIGGER task_feedback_append_only BEFORE UPDATE ON task_feedback
  FOR EACH ROW EXECUTE FUNCTION forbid_update();

-- 확인 시각 기록
CREATE TABLE view_events (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  share_link_id  uuid NOT NULL REFERENCES share_links(id) ON DELETE CASCADE,
  project_id     uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  task_id        uuid REFERENCES tasks(id) ON DELETE CASCADE,
  kind           text NOT NULL CHECK (kind IN ('open', 'stage_ack', 'deliverable')),
  viewer_name    text,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX view_events_project_idx ON view_events (project_id, created_at DESC);

-- 수정 요청: 회차는 서버가 프로젝트 행을 잠근 뒤 매긴다
CREATE TABLE revision_requests (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id       uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  task_id          uuid REFERENCES tasks(id) ON DELETE SET NULL,
  seq              integer NOT NULL,
  body             text NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
  requester_name   text NOT NULL,
  over_limit       boolean NOT NULL DEFAULT false,
  excluded_at      timestamptz,
  excluded_reason  text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, seq)
);

-- 초과 수정에 대한 추가 견적
CREATE TABLE extra_quotes (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id           uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  revision_request_id  uuid REFERENCES revision_requests(id) ON DELETE SET NULL,
  title                text NOT NULL,
  description          text,
  amount               numeric(14, 0) NOT NULL CHECK (amount >= 0),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['attachments', 'share_links', 'extra_quotes'] LOOP
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
      t || '_set_updated_at', t);
  END LOOP;
END;
$$;
