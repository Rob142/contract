"""지급 단계 계보: 수정 계약으로 이어진 옛 단계를 현재 단계와 한 묶음으로 본다 (0005)."""

# :ids 의 단계마다 (root_id=그 단계, term_id=자기 자신 또는 이어진 옛 단계) 행을 만든다
TERM_LINEAGE_CTE = """
    WITH RECURSIVE lineage(root_id, term_id) AS (
        SELECT t, t FROM unnest(CAST(:ids AS uuid[])) AS t
        UNION
        SELECT l.root_id, s.predecessor_term_id
          FROM payment_term_successions s JOIN lineage l ON s.successor_term_id = l.term_id
    )
"""
