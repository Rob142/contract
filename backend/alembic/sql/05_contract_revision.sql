-- 청구 후 계약 변경 반영 (계약_변경_반영_설계.md)
-- 발행 기록은 고치지 않고, 옛 지급 단계 → 새 지급 단계 승계를 따로 기록한다.

-- ---------------------------------------------------------------------------
-- 승계: 청구가 있던 옛 단계가 새 계약 버전의 어느 단계로 이어지는지
-- ---------------------------------------------------------------------------
CREATE TABLE payment_term_successions (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id             uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
  project_id           uuid NOT NULL,
  predecessor_term_id  uuid NOT NULL
                       REFERENCES payment_terms (id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  successor_term_id    uuid NOT NULL
                       REFERENCES payment_terms (id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  created_by           uuid REFERENCES users (id) ON DELETE SET NULL,
  created_at           timestamptz NOT NULL DEFAULT now(),
  UNIQUE (predecessor_term_id),
  CHECK (predecessor_term_id <> successor_term_id),
  FOREIGN KEY (project_id, owner_id) REFERENCES projects (id, owner_id) ON DELETE CASCADE
);
CREATE INDEX payment_term_successions_successor_idx ON payment_term_successions (successor_term_id);

-- 기록은 추가만 한다 (계정·프로젝트 삭제에 따른 연쇄 삭제는 허용)
CREATE OR REPLACE FUNCTION payment_term_successions_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'payment term succession % cannot be modified', OLD.id
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER payment_term_successions_guard
  BEFORE UPDATE ON payment_term_successions
  FOR EACH ROW EXECUTE FUNCTION payment_term_successions_guard();

-- ---------------------------------------------------------------------------
-- 단계의 실제 청구액: 자기 배분 + 이어진 옛 단계(여러 번 이어져도 모두)의 배분
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION term_billed_total(p_term uuid, p_statuses text[]) RETURNS numeric
LANGUAGE sql STABLE AS $$
  WITH RECURSIVE lineage(term_id) AS (
    SELECT p_term
    UNION
    SELECT s.predecessor_term_id
      FROM payment_term_successions s JOIN lineage l ON s.successor_term_id = l.term_id
  )
  SELECT COALESCE(sum(ba.amount), 0)
    FROM billing_allocations ba
    JOIN invoice_items ii ON ii.id = ba.invoice_item_id
    JOIN invoices i ON i.id = ii.invoice_id
   WHERE ba.payment_term_id IN (SELECT term_id FROM lineage)
     AND i.status = ANY (p_statuses);
$$;

-- ---------------------------------------------------------------------------
-- 새 불변식: 초안 배분은 프로젝트 "현재" 계약 버전의 단계에만 둘 수 있다
-- (이미 발행된 옛 배분은 그대로 유효. 발행본 배분은 invoice_children_guard가 따로 막는다)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION billing_allocations_current_term() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_term_version     uuid;
  v_project_version  uuid;
BEGIN
  IF NEW.payment_term_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT pt.contract_version_id INTO v_term_version FROM payment_terms pt WHERE pt.id = NEW.payment_term_id;
  SELECT p.contract_version_id INTO v_project_version
    FROM invoice_items ii
    JOIN invoices i ON i.id = ii.invoice_id
    JOIN projects p ON p.id = i.project_id
   WHERE ii.id = NEW.invoice_item_id;
  IF v_project_version IS DISTINCT FROM v_term_version THEN
    RAISE EXCEPTION 'payment term % is not part of the project''s current contract version', NEW.payment_term_id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER billing_allocations_current_term
  BEFORE INSERT OR UPDATE OF payment_term_id ON billing_allocations
  FOR EACH ROW EXECUTE FUNCTION billing_allocations_current_term();

-- ---------------------------------------------------------------------------
-- 발행 시점 검증: 단계 한도를 계보 전체 청구액으로 검사하도록 교체
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION invoices_check_on_issue() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_items_sum        numeric;
  v_term             record;
  v_task             record;
  v_billed           numeric;
  v_project_version  uuid;
BEGIN
  SELECT COALESCE(sum(amount), 0) INTO v_items_sum
    FROM invoice_items WHERE invoice_id = NEW.id;

  IF v_items_sum = 0 THEN
    RAISE EXCEPTION 'invoice % has no billable items', NEW.id USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.subtotal <> v_items_sum THEN
    RAISE EXCEPTION 'invoice % subtotal % does not match items sum %', NEW.id, NEW.subtotal, v_items_sum
      USING ERRCODE = 'check_violation';
  END IF;

  SELECT contract_version_id INTO v_project_version FROM projects WHERE id = NEW.project_id;

  -- 지급 단계별 한도 (옛 계약에서 이어진 청구 포함)
  FOR v_term IN
    SELECT DISTINCT pt.id, pt.amount, pt.label, pt.contract_version_id
      FROM billing_allocations ba
      JOIN invoice_items ii ON ii.id = ba.invoice_item_id
      JOIN payment_terms pt ON pt.id = ba.payment_term_id
     WHERE ii.invoice_id = NEW.id
     ORDER BY pt.id
  LOOP
    IF v_term.contract_version_id IS DISTINCT FROM v_project_version THEN
      RAISE EXCEPTION 'payment term "%" belongs to a previous contract version', v_term.label
        USING ERRCODE = 'check_violation';
    END IF;
    PERFORM 1 FROM payment_terms WHERE id = v_term.id FOR UPDATE;

    v_billed := term_billed_total(v_term.id, ARRAY['issued']);
    IF v_billed > v_term.amount THEN
      RAISE EXCEPTION 'payment term "%" over-billed: % > %', v_term.label, v_billed, v_term.amount
        USING ERRCODE = 'check_violation';
    END IF;
  END LOOP;

  -- 시간과 단가가 확정된 작업은 그 금액이 한도
  FOR v_task IN
    SELECT DISTINCT t.id, t.title, round(t.hours * t.hourly_rate) AS cap
      FROM billing_allocations ba
      JOIN invoice_items ii ON ii.id = ba.invoice_item_id
      JOIN tasks t ON t.id = ba.task_id
     WHERE ii.invoice_id = NEW.id
       AND t.hours IS NOT NULL AND t.hourly_rate IS NOT NULL
     ORDER BY t.id
  LOOP
    PERFORM 1 FROM tasks WHERE id = v_task.id FOR UPDATE;

    SELECT COALESCE(sum(ba.amount), 0) INTO v_billed
      FROM billing_allocations ba
      JOIN invoice_items ii ON ii.id = ba.invoice_item_id
      JOIN invoices i ON i.id = ii.invoice_id
     WHERE ba.task_id = v_task.id
       AND i.status = 'issued';

    IF v_billed > v_task.cap THEN
      RAISE EXCEPTION 'task "%" over-billed: % > %', v_task.title, v_billed, v_task.cap
        USING ERRCODE = 'check_violation';
    END IF;
  END LOOP;

  RETURN NEW;
END;
$$;
