/** 한글 조사 고르기: 마지막 글자에 받침이 있는지로 갈린다. 한글이 아니면 받침 없는 쪽을 쓴다. */
function hasFinalConsonant(word: string): boolean {
  const last = word.trim().at(-1)
  if (!last) return false
  const code = last.charCodeAt(0)
  if (code < 0xac00 || code > 0xd7a3) return false
  return (code - 0xac00) % 28 !== 0
}

/** 을/를만 */
export const eulReul = (word: string): string => (hasFinalConsonant(word) ? '을' : '를')

/** 이/가만 */
export const iGa = (word: string): string => (hasFinalConsonant(word) ? '이' : '가')

/** 단어 뒤에 을/를을 붙인다 */
export const withEulReul = (word: string): string => `${word}${eulReul(word)}`

/** 단어 뒤에 이/가를 붙인다 */
export const withIGa = (word: string): string => `${word}${iGa(word)}`
