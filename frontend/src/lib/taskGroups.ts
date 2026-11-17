/** 날짜가 있는 작업 중 같은 마감일이 2개 이상인 경우에만 묶는다. */
export function groupTasksByDeadline<T extends { id: string; due_date: string | null }>(tasks: T[]) {
  const dates = new Map<string, T[]>()
  for (const task of tasks) {
    if (task.due_date) dates.set(task.due_date, [...(dates.get(task.due_date) ?? []), task])
  }
  const seen = new Set<string>()
  return tasks.flatMap((task) => {
    const grouped = Boolean(task.due_date && (dates.get(task.due_date)?.length ?? 0) > 1)
    if (grouped && seen.has(task.due_date!)) return []
    if (grouped) seen.add(task.due_date!)
    return [{
      key: grouped ? `date-${task.due_date}` : task.id,
      dueDate: task.due_date,
      grouped,
      tasks: grouped ? dates.get(task.due_date!)! : [task],
    }]
  })
}
