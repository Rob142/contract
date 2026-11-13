import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import './styles/app.css'

import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import { meKey } from './api/auth'
import { ApiError } from './api/client'
import { App } from './App'

const queryClient: QueryClient = new QueryClient({
  queryCache: new QueryCache({
    // 어떤 요청이든 401이면 세션이 끝난 것: 로그인 상태를 비워 로그인 화면으로 보낸다
    onError: (error) => {
      if (error instanceof ApiError && error.status === 401) queryClient.setQueryData(meKey, null)
    },
  }),
  defaultOptions: {
    queries: {
      retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
