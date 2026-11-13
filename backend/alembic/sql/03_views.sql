-- 화면 지표용 뷰. 진행률·미수액을 한 곳에서 계산해 화면마다 값이 달라지지 않게 한다.


-- 인보이스별 입금·잔액. 입금 상태와 연체는 별도로 산정한다(설계서 6장).
CREATE VIEW v_invoice_balances WITH (security_invoker = true) AS
SELECT
  i.id          AS invoice_id,
  i.owner_id,
  i.project_id,
  i.invoice_no,
  i.status,
  i.due_date,
  i.total,
  COALESCE(p.paid, 0)                AS paid_amount,
  i.total - COALESCE(p.paid, 0)      AS balance,
  CASE
    WHEN i.status <> 'issued'              THEN NULL
    WHEN COALESCE(p.paid, 0) >= i.total    THEN 'paid'
    WHEN COALESCE(p.paid, 0) > 0           THEN 'partial'
    ELSE 'unpaid'
  END                                AS payment_status,
  (i.status = 'issued'
   AND COALESCE(p.paid, 0) < i.total
   AND i.due_date < current_date)    AS is_overdue
FROM invoices i
LEFT JOIN (
  SELECT invoice_id, sum(amount) AS paid
    FROM payments
   WHERE voided_at IS NULL
   GROUP BY invoice_id
) p ON p.invoice_id = i.id;

-- 프로젝트별 진행률과 금액 지표. 진행률은 청구 비율로 쓰지 않는다.
CREATE VIEW v_project_summary WITH (security_invoker = true) AS
SELECT
  pr.id                              AS project_id,
  pr.owner_id,
  pr.status,
  pr.due_date,
  pr.contract_amount,
  COALESCE(t.total_tasks, 0)         AS total_tasks,
  COALESCE(t.done_tasks, 0)          AS done_tasks,
  CASE WHEN COALESCE(t.total_tasks, 0) = 0 THEN NULL   -- 작업 없음 = 산정 전
       ELSE round(t.done_tasks * 100.0 / t.total_tasks)
  END                                AS progress_pct,
  COALESCE(b.billed, 0)              AS billed_amount,
  COALESCE(b.paid, 0)                AS paid_amount,
  COALESCE(b.billed, 0) - COALESCE(b.paid, 0) AS outstanding_amount
FROM projects pr
LEFT JOIN (
  SELECT project_id,
         count(*)                                AS total_tasks,
         count(*) FILTER (WHERE status = 'done') AS done_tasks
    FROM tasks
   GROUP BY project_id
) t ON t.project_id = pr.id
LEFT JOIN (
  SELECT project_id, sum(total) AS billed, sum(paid_amount) AS paid
    FROM v_invoice_balances
   WHERE status = 'issued'
   GROUP BY project_id
) b ON b.project_id = pr.id;

-- 계약서 목록: 최신 버전의 처리 상태
CREATE VIEW v_contract_latest WITH (security_invoker = true) AS
SELECT DISTINCT ON (c.id)
  c.id          AS contract_id,
  c.owner_id,
  c.title,
  c.job_type,
  cv.id         AS contract_version_id,
  cv.version_no,
  cv.status,
  cv.created_at AS uploaded_at
FROM contracts c
JOIN contract_versions cv ON cv.contract_id = c.id
ORDER BY c.id, cv.version_no DESC;

