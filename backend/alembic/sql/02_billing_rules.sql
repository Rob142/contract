-- 청구·입금 무결성 규칙 (설계서 6·9장)
-- 서비스 계층 검증과 별개로 DB에서도 마지막으로 막는다.


-- ---------------------------------------------------------------------------
-- 발행된 인보이스는 수정 불가. 허용되는 변경은 issued → cancelled 뿐이다.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION invoices_guard_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = 'cancelled' THEN
    RAISE EXCEPTION 'cancelled invoice % cannot be modified', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;

  IF OLD.status = 'issued' THEN
    IF NEW.status <> 'cancelled'
       OR (to_jsonb(NEW) - ARRAY['status', 'cancelled_at', 'cancel_reason', 'updated_at'])
          IS DISTINCT FROM
          (to_jsonb(OLD) - ARRAY['status', 'cancelled_at', 'cancel_reason', 'updated_at']) THEN
      RAISE EXCEPTION 'issued invoice % is immutable; cancel and reissue instead', OLD.id
        USING ERRCODE = 'check_violation';
    END IF;
    IF EXISTS (SELECT 1 FROM payments p WHERE p.invoice_id = OLD.id AND p.voided_at IS NULL) THEN
      RAISE EXCEPTION 'invoice % has active payments; void them before cancelling', OLD.id
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;

  IF OLD.status = 'draft' AND NEW.status = 'cancelled' THEN
    RAISE EXCEPTION 'draft invoice % should be deleted, not cancelled', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER invoices_guard_update
  BEFORE UPDATE ON invoices
  FOR EACH ROW EXECUTE FUNCTION invoices_guard_update();

CREATE OR REPLACE FUNCTION invoices_guard_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status <> 'draft' THEN
    RAISE EXCEPTION 'only draft invoices can be deleted (invoice %)', OLD.id
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN OLD;
END;
$$;

CREATE TRIGGER invoices_guard_delete
  BEFORE DELETE ON invoices
  FOR EACH ROW EXECUTE FUNCTION invoices_guard_delete();

-- 초안이 아닌 인보이스의 항목·배분은 바꿀 수 없다
CREATE OR REPLACE FUNCTION invoice_children_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_invoice_id uuid;
  v_status     text;
BEGIN
  IF TG_TABLE_NAME = 'invoice_items' THEN
    v_invoice_id := COALESCE(NEW.invoice_id, OLD.invoice_id);
  ELSE
    SELECT ii.invoice_id INTO v_invoice_id
      FROM invoice_items ii
     WHERE ii.id = COALESCE(NEW.invoice_item_id, OLD.invoice_item_id);
  END IF;

  SELECT status INTO v_status FROM invoices WHERE id = v_invoice_id;
  -- 초안 삭제로 인한 연쇄 삭제는 부모가 이미 사라져 v_status가 NULL이다
  IF v_status IS NOT NULL AND v_status <> 'draft' THEN
    RAISE EXCEPTION 'invoice % is %; its items cannot change', v_invoice_id, v_status
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE TRIGGER invoice_items_guard
  BEFORE INSERT OR UPDATE OR DELETE ON invoice_items
  FOR EACH ROW EXECUTE FUNCTION invoice_children_guard();

CREATE TRIGGER billing_allocations_guard
  BEFORE INSERT OR UPDATE OR DELETE ON billing_allocations
  FOR EACH ROW EXECUTE FUNCTION invoice_children_guard();

-- ---------------------------------------------------------------------------
-- 발행 시점 검증: 합계 일치, 지급 단계·작업별 초과 청구 차단
-- 지급 단계 행을 FOR UPDATE로 잠가 동시 발행도 직렬화한다.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION invoices_check_on_issue() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_items_sum  numeric;
  v_term       record;
  v_task       record;
  v_billed     numeric;
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

  -- 지급 단계별 한도
  FOR v_term IN
    SELECT DISTINCT pt.id, pt.amount, pt.label
      FROM billing_allocations ba
      JOIN invoice_items ii ON ii.id = ba.invoice_item_id
      JOIN payment_terms pt ON pt.id = ba.payment_term_id
     WHERE ii.invoice_id = NEW.id
     ORDER BY pt.id
  LOOP
    PERFORM 1 FROM payment_terms WHERE id = v_term.id FOR UPDATE;

    SELECT COALESCE(sum(ba.amount), 0) INTO v_billed
      FROM billing_allocations ba
      JOIN invoice_items ii ON ii.id = ba.invoice_item_id
      JOIN invoices i ON i.id = ii.invoice_id
     WHERE ba.payment_term_id = v_term.id
       AND i.status = 'issued';

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

CREATE TRIGGER invoices_check_on_issue
  AFTER UPDATE OF status ON invoices
  FOR EACH ROW
  WHEN (OLD.status = 'draft' AND NEW.status = 'issued')
  EXECUTE FUNCTION invoices_check_on_issue();

-- ---------------------------------------------------------------------------
-- 입금: 발행된 인보이스에만, 잔액 초과 금지. 기록 후에는 취소(void)만 허용
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION payments_guard_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  v_inv   record;
  v_paid  numeric;
BEGIN
  SELECT id, status, total INTO v_inv FROM invoices WHERE id = NEW.invoice_id FOR UPDATE;

  IF v_inv.status <> 'issued' THEN
    RAISE EXCEPTION 'payments can only be recorded on issued invoices (invoice % is %)', v_inv.id, v_inv.status
      USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.voided_at IS NOT NULL THEN
    RAISE EXCEPTION 'a payment cannot be created already voided' USING ERRCODE = 'check_violation';
  END IF;

  SELECT COALESCE(sum(amount), 0) INTO v_paid
    FROM payments WHERE invoice_id = NEW.invoice_id AND voided_at IS NULL;

  IF v_paid + NEW.amount > v_inv.total THEN
    RAISE EXCEPTION 'overpayment: paid % + new % > total %', v_paid, NEW.amount, v_inv.total
      USING ERRCODE = 'check_violation';
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER payments_guard_insert
  BEFORE INSERT ON payments
  FOR EACH ROW EXECUTE FUNCTION payments_guard_insert();

CREATE OR REPLACE FUNCTION payments_guard_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.voided_at IS NOT NULL THEN
    RAISE EXCEPTION 'voided payment % cannot be modified', OLD.id USING ERRCODE = 'check_violation';
  END IF;
  IF NEW.voided_at IS NULL
     OR (to_jsonb(NEW) - ARRAY['voided_at', 'void_reason', 'updated_at'])
        IS DISTINCT FROM
        (to_jsonb(OLD) - ARRAY['voided_at', 'void_reason', 'updated_at']) THEN
    RAISE EXCEPTION 'payment % can only be voided, not edited', OLD.id USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER payments_guard_update
  BEFORE UPDATE ON payments
  FOR EACH ROW EXECUTE FUNCTION payments_guard_update();

CREATE OR REPLACE FUNCTION payments_guard_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'payments are never deleted; void payment % instead', OLD.id
    USING ERRCODE = 'check_violation';
END;
$$;

CREATE TRIGGER payments_guard_delete
  BEFORE DELETE ON payments
  FOR EACH ROW EXECUTE FUNCTION payments_guard_delete();

-- 입금 취소 시 해당 입금으로 만든 확인 문서는 무효 처리
CREATE OR REPLACE FUNCTION payments_invalidate_documents() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  UPDATE generated_documents SET is_valid = false WHERE payment_id = NEW.id;
  RETURN NEW;
END;
$$;

CREATE TRIGGER payments_invalidate_documents
  AFTER UPDATE OF voided_at ON payments
  FOR EACH ROW
  WHEN (OLD.voided_at IS NULL AND NEW.voided_at IS NOT NULL)
  EXECUTE FUNCTION payments_invalidate_documents();

