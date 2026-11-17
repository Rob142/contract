/** 달력의 날짜는 UTC 날짜 연산으로만 계산해 시간대에 따른 하루 밀림을 막는다. */
export function shiftMonth(month: string, offset: number): string {
  const [year, value] = month.split('-').map(Number)
  return new Date(Date.UTC(year!, value! - 1 + offset, 1)).toISOString().slice(0, 7)
}

export function monthCells(month: string) {
  const [year, value] = month.split('-').map(Number)
  const first = new Date(Date.UTC(year!, value! - 1, 1))
  const start = 1 - first.getUTCDay()
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(Date.UTC(year!, value! - 1, start + index)).toISOString().slice(0, 10)
    return { date, day: Number(date.slice(8)), inMonth: date.startsWith(month) }
  })
}
