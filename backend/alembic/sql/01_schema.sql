-- Freelance Hub MVP 스키마 (TODO: DB-01 ~ DB-22)
-- 원칙: UUID PK, created_at/updated_at, 금액 numeric(14,0) KRW 원 단위,
--       상태값은 text + CHECK, 같은 소유자끼리만 연결(복합 FK (id, owner_id)).


-- ---------------------------------------------------------------------------
-- 공통 함수
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------
-- 1-1. 기반: 사용자, 세션, 거래처, 파일, 감사 기록, 재전송 키
-- ---------------------------------------------------------------------------
CREATE TABLE users (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email                text NOT NULL,
  password_hash        text NOT NULL,
  name                 text NOT NULL,
  job_type             text NOT NULL DEFAULT 'design'
                       CHECK (job_type IN ('dev', 'design', 'video', 'marketing')),
  default_llm_mode     text NOT NULL DEFAULT 'ask'
                       CHECK (default_llm_mode IN ('ask', 'commercial', 'local')),
  -- 문서 발행 정보 (발행 시 인보이스 스냅샷으로 복사된다)
  issuer_name          text,
  issuer_display_name  text,
  issuer_contact       text,
  bank_name            text,
  bank_account         text,
  terms_agreed_at      timestamptz NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX users_email_uq ON users (lower(email));

CREATE TABLE user_sessions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  token_hash    text NOT NULL UNIQUE,
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,
  user_agent    text,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX user_sessions_user_idx ON user_sessions (user_id);

CREATE TABLE clients (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  name           text NOT NULL,
  contact_name   text,
  contact_email  text,
  contact_phone  text,
  memo           text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, owner_id)
);
CREATE INDEX clients_owner_idx ON clients (owner_id);

CREATE TABLE files (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id       uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  storage_kind   text NOT NULL DEFAULT 'local' CHECK (storage_kind IN ('local', 'supabase')),
  object_key     text NOT NULL UNIQUE,          -- 절대 경로가 아닌 저장소 객체 키
  size_bytes     bigint NOT NULL CHECK (size_bytes >= 0),
  sha256         char(64) NOT NULL,
  mime_type      text NOT NULL,
  original_name  text NOT NULL,
  deleted_at     timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, owner_id)
);
CREATE INDEX files_owner_idx ON files (owner_id);

CREATE TABLE audit_events (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id     uuid REFERENCES users (id) ON DELETE SET NULL,
  action       text NOT NULL,                  -- invoice.issue, payment.void ...
  target_type  text NOT NULL,
  target_id    uuid NOT NULL,
  summary      jsonb NOT NULL DEFAULT '{}'::jsonb,  -- 본문·개인정보 금지
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_events_target_idx ON audit_events (target_type, target_id);
CREATE INDEX audit_events_actor_idx ON audit_events (actor_id, created_at DESC);

CREATE TABLE idempotency_keys (
  owner_id         uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  key              text NOT NULL,
  request_hash     char(64) NOT NULL,
  response_status  integer,
  response_body    jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (owner_id, key)
);

-- ---------------------------------------------------------------------------
-- 1-3. 계약서 (프로젝트가 계약 버전을 참조하므로 먼저 생성)
-- ---------------------------------------------------------------------------
CREATE TABLE contracts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  client_id   uuid,
  title       text NOT NULL,
  job_type    text NOT NULL CHECK (job_type IN ('dev', 'design', 'video', 'marketing')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, owner_id),
  FOREIGN KEY (client_id, owner_id) REFERENCES clients (id, owner_id) ON DELETE RESTRICT
);
CREATE INDEX contracts_owner_idx ON contracts (owner_id, created_at DESC);

CREATE TABLE contract_versions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_id  uuid NOT NULL,
  owner_id     uuid NOT NULL,
  version_no   integer NOT NULL CHECK (version_no >= 1),
  file_id      uuid NOT NULL,
  sha256       char(64) NOT NULL,
  page_count   integer CHECK (page_count >= 0),
  status       text NOT NULL DEFAULT 'uploaded'
               CHECK (status IN ('uploaded', 'extracting', 'needs_review', 'ready',
                                 'analyzing', 'analyzed', 'failed')),
  failure_reason text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (contract_id, version_no),
  UNIQUE (id, owner_id),
  FOREIGN KEY (contract_id, owner_id) REFERENCES contracts (id, owner_id) ON DELETE CASCADE,
  FOREIGN KEY (file_id, owner_id) REFERENCES files (id, owner_id) ON DELETE RESTRICT
);

CREATE TABLE contract_pages (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_version_id  uuid NOT NULL REFERENCES contract_versions (id) ON DELETE CASCADE,
  page_no              integer NOT NULL CHECK (page_no >= 1),
  extraction_method    text NOT NULL CHECK (extraction_method IN ('text', 'ocr')),
  quality_score        numeric(4,3) CHECK (quality_score BETWEEN 0 AND 1),
  needs_review         boolean NOT NULL DEFAULT false,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (contract_version_id, page_no)
);

-- 원본 추출본(extracted)과 사용자 수정본(user_edited)을 버전으로 구분
CREATE TABLE contract_text_versions (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_version_id  uuid NOT NULL REFERENCES contract_versions (id) ON DELETE CASCADE,
  version_no           integer NOT NULL CHECK (version_no >= 1),
  kind                 text NOT NULL CHECK (kind IN ('extracted', 'user_edited')),
  based_on_id          uuid REFERENCES contract_text_versions (id) ON DELETE RESTRICT,
  edited_by            uuid REFERENCES users (id) ON DELETE SET NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (contract_version_id, version_no),
  CHECK (kind = 'extracted' OR (based_on_id IS NOT NULL AND edited_by IS NOT NULL))
);

CREATE TABLE contract_text_blocks (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  text_version_id  uuid NOT NULL REFERENCES contract_text_versions (id) ON DELETE CASCADE,
  page_no          integer NOT NULL CHECK (page_no >= 1),
  block_key        text NOT NULL,              -- 근거 추적용 안정 식별자 (예: p1-b07)
  position         integer NOT NULL,           -- 페이지 내 읽기 순서
  bbox             jsonb,                      -- {x0, y0, x1, y1}
  text             text NOT NULL,
  UNIQUE (text_version_id, block_key)
);
CREATE INDEX contract_text_blocks_page_idx ON contract_text_blocks (text_version_id, page_no, position);

CREATE TABLE contract_fields (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_version_id  uuid NOT NULL REFERENCES contract_versions (id) ON DELETE CASCADE,
  field_key            text NOT NULL,          -- contract_amount, final_due_date, payment_terms, revision_count ...
  extracted_value      text,
  confirmed_value      text,
  evidence_block_id    uuid REFERENCES contract_text_blocks (id) ON DELETE SET NULL,
  status               text NOT NULL DEFAULT 'unconfirmed'
                       CHECK (status IN ('unconfirmed', 'confirmed')),
  confirmed_by         uuid REFERENCES users (id) ON DELETE SET NULL,
  confirmed_at         timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (contract_version_id, field_key),
  CHECK (status = 'unconfirmed' OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL))
);

CREATE TABLE payment_terms (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contract_version_id  uuid NOT NULL REFERENCES contract_versions (id) ON DELETE CASCADE,
  seq                  integer NOT NULL CHECK (seq >= 1),
  stage                text NOT NULL CHECK (stage IN ('deposit', 'interim', 'balance', 'other')),
  label                text NOT NULL,          -- 선금 50%
  ratio                numeric(5,2) CHECK (ratio > 0 AND ratio <= 100),
  amount               numeric(14,0) NOT NULL CHECK (amount >= 0),
  requirement          text,                   -- 계약 체결 후 / 검수 완료 후
  due_date             date,
  confirmed_by         uuid REFERENCES users (id) ON DELETE SET NULL,
  confirmed_at         timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (contract_version_id, seq)
);

-- ---------------------------------------------------------------------------
-- 1-2. 프로젝트·작업
-- ---------------------------------------------------------------------------
CREATE TABLE projects (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id             uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  client_id            uuid NOT NULL,
  contract_version_id  uuid,
  name                 text NOT NULL,
  job_type             text NOT NULL CHECK (job_type IN ('dev', 'design', 'video', 'marketing')),
  start_date           date,
  due_date             date,
  contract_amount      numeric(14,0) NOT NULL DEFAULT 0 CHECK (contract_amount >= 0),
  currency             char(3) NOT NULL DEFAULT 'KRW' CHECK (currency = 'KRW'),
  status               text NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'completed', 'archived')),
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, owner_id),
  CHECK (due_date IS NULL OR start_date IS NULL OR due_date >= start_date),
  FOREIGN KEY (client_id, owner_id) REFERENCES clients (id, owner_id) ON DELETE RESTRICT,
  FOREIGN KEY (contract_version_id, owner_id) REFERENCES contract_versions (id, owner_id) ON DELETE RESTRICT
);
CREATE INDEX projects_owner_idx ON projects (owner_id, status, due_date);

CREATE TABLE tasks (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id    uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  title         text NOT NULL,
  label         text,                          -- 디자인, 납품, 기획 ...
  status        text NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'doing', 'done')),
  position      integer NOT NULL DEFAULT 0,    -- 칸반 열 안의 순서
  due_date      date,
  completed_at  timestamptz,
  hours         numeric(8,2) CHECK (hours >= 0),
  hourly_rate   numeric(14,0) CHECK (hourly_rate >= 0),
  source        text NOT NULL DEFAULT 'manual'
                CHECK (source IN ('contract', 'estimated', 'manual')),
  source_note   text,                          -- 계약서 제1조에 근거
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'done') = (completed_at IS NOT NULL))
);
CREATE INDEX tasks_project_idx ON tasks (project_id, status, position);
CREATE INDEX tasks_due_idx ON tasks (due_date) WHERE status <> 'done';

CREATE TABLE task_checklist_items (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id     uuid NOT NULL REFERENCES tasks (id) ON DELETE CASCADE,
  content     text NOT NULL,
  is_done     boolean NOT NULL DEFAULT false,
  position    integer NOT NULL DEFAULT 0,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX task_checklist_items_task_idx ON task_checklist_items (task_id, position);

CREATE TABLE attachments (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  uuid NOT NULL REFERENCES projects (id) ON DELETE CASCADE,
  task_id     uuid REFERENCES tasks (id) ON DELETE CASCADE,
  file_id     uuid NOT NULL REFERENCES files (id) ON DELETE RESTRICT,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX attachments_project_idx ON attachments (project_id);

-- ---------------------------------------------------------------------------
-- 1-3. 분석 작업·결과
-- ---------------------------------------------------------------------------
CREATE TABLE analysis_jobs (
  id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id                    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  contract_version_id         uuid NOT NULL,
  text_version_id             uuid REFERENCES contract_text_versions (id) ON DELETE RESTRICT,
  kind                        text NOT NULL CHECK (kind IN ('extract', 'analyze', 'revision_prompt')),
  status                      text NOT NULL DEFAULT 'queued'
                              CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  stage                       text CHECK (stage IN ('extracting', 'ocr', 'analyzing', 'validating', 'generating')),
  job_type                    text CHECK (job_type IN ('dev', 'design', 'video', 'marketing')),
  llm_mode                    text CHECK (llm_mode IN ('commercial', 'local')),
  model_config                jsonb NOT NULL DEFAULT '{}'::jsonb,   -- API 키 저장 금지
  rules_version               text,
  prompt_version              text,
  input                       jsonb NOT NULL DEFAULT '{}'::jsonb,   -- 수정 프롬프트 대상 결과 ID 등
  reuse_key                   text,
  external_send_consented_at  timestamptz,
  run_id                      uuid,
  attempts                    integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  max_attempts                integer NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
  heartbeat_at                timestamptz,
  lease_expires_at            timestamptz,
  started_at                  timestamptz,
  finished_at                 timestamptz,
  cancel_requested_at         timestamptz,
  error_code                  text,
  error_message               text,
  created_at                  timestamptz NOT NULL DEFAULT now(),
  updated_at                  timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (contract_version_id, owner_id) REFERENCES contract_versions (id, owner_id) ON DELETE CASCADE,
  -- 분석·프롬프트 작업은 텍스트 버전과 실행 방식이 필수
  CHECK (kind = 'extract' OR (text_version_id IS NOT NULL AND llm_mode IS NOT NULL AND job_type IS NOT NULL)),
  -- 상용 모델은 외부 전송 동의 후에만
  CHECK (llm_mode IS DISTINCT FROM 'commercial' OR external_send_consented_at IS NOT NULL),
  CHECK (status <> 'running' OR (run_id IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE INDEX analysis_jobs_queue_idx ON analysis_jobs (created_at) WHERE status = 'queued';
CREATE INDEX analysis_jobs_lease_idx ON analysis_jobs (lease_expires_at) WHERE status = 'running';
CREATE INDEX analysis_jobs_owner_idx ON analysis_jobs (owner_id, created_at DESC);
CREATE INDEX analysis_jobs_reuse_idx ON analysis_jobs (owner_id, reuse_key) WHERE status = 'succeeded';

CREATE TABLE analysis_results (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id             uuid NOT NULL REFERENCES analysis_jobs (id) ON DELETE CASCADE,
  rule_id            text NOT NULL,            -- DES-001
  rule_version       text NOT NULL,
  status             text NOT NULL CHECK (status IN ('found', 'not_found', 'unclear')),
  review_level       text NOT NULL CHECK (review_level IN ('caution', 'needs_check', 'confirmed')),
  title              text NOT NULL,
  explanation        text NOT NULL,
  user_action        text,
  suggestion         text,
  evidence           jsonb NOT NULL DEFAULT '[]'::jsonb,  -- [{page_no, block_key, quote}]
  validation_status  text NOT NULL DEFAULT 'pending'
                     CHECK (validation_status IN ('pending', 'passed', 'failed')),
  model_id           text NOT NULL,
  raw_response       jsonb,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, rule_id)
);

CREATE TABLE revision_prompts (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id               uuid NOT NULL UNIQUE REFERENCES analysis_jobs (id) ON DELETE CASCADE,
  selected_result_ids  uuid[] NOT NULL,
  content              text NOT NULL,
  model_id             text NOT NULL,
  created_at           timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 1-4. 청구·입금
-- ---------------------------------------------------------------------------
CREATE TABLE invoices (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id             uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  project_id           uuid NOT NULL,
  invoice_no           text,                   -- 발행 시 부여 (INV-2026-011)
  status               text NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft', 'issued', 'cancelled')),
  title                text NOT NULL,          -- 디자인 잔금
  issue_date           date,
  due_date             date,
  currency             char(3) NOT NULL DEFAULT 'KRW' CHECK (currency = 'KRW'),
  subtotal             numeric(14,0) NOT NULL DEFAULT 0 CHECK (subtotal >= 0),
  tax_amount           numeric(14,0) NOT NULL DEFAULT 0 CHECK (tax_amount >= 0),
  withholding_amount   numeric(14,0) NOT NULL DEFAULT 0 CHECK (withholding_amount >= 0),
  adjustment_note      text,
  total                numeric(14,0) NOT NULL DEFAULT 0 CHECK (total >= 0),
  snapshot             jsonb,                  -- 발행 시 거래처·발행자·조건 고정
  replaces_invoice_id  uuid REFERENCES invoices (id) ON DELETE RESTRICT,
  issued_at            timestamptz,
  cancelled_at         timestamptz,
  cancel_reason        text,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (id, owner_id),
  FOREIGN KEY (project_id, owner_id) REFERENCES projects (id, owner_id) ON DELETE RESTRICT,
  CHECK (total = subtotal + tax_amount - withholding_amount),
  CHECK (status = 'draft' OR (invoice_no IS NOT NULL AND issue_date IS NOT NULL
                              AND due_date IS NOT NULL AND snapshot IS NOT NULL AND issued_at IS NOT NULL)),
  CHECK (status <> 'cancelled' OR cancelled_at IS NOT NULL)
);
CREATE UNIQUE INDEX invoices_no_uq ON invoices (owner_id, invoice_no) WHERE invoice_no IS NOT NULL;
CREATE INDEX invoices_owner_idx ON invoices (owner_id, status, due_date);
CREATE INDEX invoices_project_idx ON invoices (project_id);

CREATE TABLE invoice_items (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id   uuid NOT NULL REFERENCES invoices (id) ON DELETE CASCADE,
  position     integer NOT NULL DEFAULT 0,
  kind         text NOT NULL CHECK (kind IN ('payment_stage', 'task', 'hourly', 'extra')),
  description  text NOT NULL,
  detail       text,
  quantity     numeric(10,2) NOT NULL DEFAULT 1 CHECK (quantity > 0),
  unit_price   numeric(14,0) NOT NULL CHECK (unit_price >= 0),
  amount       numeric(14,0) NOT NULL CHECK (amount >= 0),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (amount = round(quantity * unit_price))   -- 원 단위 반올림
);
CREATE INDEX invoice_items_invoice_idx ON invoice_items (invoice_id, position);

-- 청구 항목 → 지급 단계 또는 작업 배분. 중복·초과 청구 검증의 기준
CREATE TABLE billing_allocations (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_item_id  uuid NOT NULL REFERENCES invoice_items (id) ON DELETE CASCADE,
  payment_term_id  uuid REFERENCES payment_terms (id) ON DELETE RESTRICT,
  task_id          uuid REFERENCES tasks (id) ON DELETE RESTRICT,
  amount           numeric(14,0) NOT NULL CHECK (amount >= 0),
  created_at       timestamptz NOT NULL DEFAULT now(),
  CHECK (num_nonnulls(payment_term_id, task_id) = 1)
);
CREATE INDEX billing_allocations_term_idx ON billing_allocations (payment_term_id) WHERE payment_term_id IS NOT NULL;
CREATE INDEX billing_allocations_task_idx ON billing_allocations (task_id) WHERE task_id IS NOT NULL;

CREATE TABLE payments (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invoice_id   uuid NOT NULL REFERENCES invoices (id) ON DELETE RESTRICT,
  amount       numeric(14,0) NOT NULL CHECK (amount > 0),
  paid_on      date NOT NULL,
  method       text NOT NULL DEFAULT 'bank_transfer'
               CHECK (method IN ('bank_transfer', 'cash', 'card', 'other')),
  memo         text,
  recorded_by  uuid NOT NULL REFERENCES users (id) ON DELETE RESTRICT,
  voided_at    timestamptz,
  void_reason  text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now(),
  CHECK (voided_at IS NULL OR void_reason IS NOT NULL)
);
CREATE INDEX payments_invoice_idx ON payments (invoice_id) WHERE voided_at IS NULL;

-- 인보이스 PDF, 일반 영수증, 입금확인서
CREATE TABLE generated_documents (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('invoice', 'receipt', 'payment_confirmation')),
  invoice_id  uuid NOT NULL REFERENCES invoices (id) ON DELETE RESTRICT,
  payment_id  uuid REFERENCES payments (id) ON DELETE RESTRICT,
  version     integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  file_id     uuid NOT NULL,
  is_valid    boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (file_id, owner_id) REFERENCES files (id, owner_id) ON DELETE RESTRICT,
  CHECK ((kind = 'invoice') = (payment_id IS NULL))
);
CREATE UNIQUE INDEX generated_documents_version_uq
  ON generated_documents (kind, invoice_id, COALESCE(payment_id, '00000000-0000-0000-0000-000000000000'::uuid), version);

-- ---------------------------------------------------------------------------
-- updated_at 트리거
-- ---------------------------------------------------------------------------
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'users', 'clients', 'files', 'contracts', 'contract_versions', 'contract_pages',
    'contract_fields', 'payment_terms', 'projects', 'tasks', 'task_checklist_items',
    'analysis_jobs', 'invoices', 'invoice_items', 'payments'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
      t || '_set_updated_at', t);
  END LOOP;
END;
$$;

