import { describe, expect, it } from 'vitest'

import { eulReul, iGa, withEulReul, withIGa } from './korean'

describe('조사 고르기', () => {
  it('받침이 있으면 을/이, 없으면 를/가', () => {
    expect(withEulReul('시안 제작')).toBe('시안 제작을')
    expect(withEulReul('수정')).toBe('수정을')
    expect(withEulReul('착수·자료 수령')).toBe('착수·자료 수령을')
    expect(withEulReul('최종 납품')).toBe('최종 납품을')
    expect(withEulReul('설계')).toBe('설계를')
    expect(withIGa('박지현 대리')).toBe('박지현 대리가')
    expect(withIGa('클라이언트')).toBe('클라이언트가')
  })

  it('따옴표로 감싼 단어는 따옴표 앞 글자로 고른다', () => {
    const title = '시안 제작'
    expect(`‘${title}’${eulReul(title)}`).toBe('‘시안 제작’을')
    expect(`‘수정’${iGa('수정')}`).toBe('‘수정’이')
  })

  it('한글이 아니거나 비어 있으면 받침 없는 쪽을 쓴다', () => {
    expect(withEulReul('QA')).toBe('QA를')
    expect(withEulReul('')).toBe('를')
  })
})
