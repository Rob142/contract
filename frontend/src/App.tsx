import { ClientServicePage, ClientInvitePage, ClientHome, ProfileEditor } from './pages/ClientServicePage'
import { FreelancerInquiriesPage } from './pages/InquiriesView'
import { Route, Routes } from 'react-router'

import { EntryPage, GuestOnly, RequireAuth } from './components/RouteGuards'
import { ClientSharePage } from './pages/ClientSharePage'
import { PortfolioPage } from './pages/PortfolioPage'
import { PublicPortfolioPage } from './pages/PublicPortfolioPage'
import { SettlementPage } from './pages/SettlementPage'
import { AnalysisPage } from './pages/AnalysisPage'
import { ContractProjectPage } from './pages/ContractProjectPage'
import { ContractDetailPage } from './pages/ContractDetailPage'
import { ContractsPage } from './pages/ContractsPage'
import { DashboardPage } from './pages/DashboardPage'
import { InvoiceDetailPage } from './pages/InvoiceDetailPage'
import { InvoiceFormPage } from './pages/InvoiceFormPage'
import { InvoicesPage } from './pages/InvoicesPage'
import { LoginPage } from './pages/LoginPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { RevisionPage } from './pages/RevisionPage'
import { ProjectDetailPage } from './pages/ProjectDetailPage'
import { ProjectsPage } from './pages/ProjectsPage'
import { RegisterPage } from './pages/RegisterPage'
import { SettingsPage } from './pages/SettingsPage'

export function App() {
  return (
    <Routes>
      <Route path="share/:token" element={<ClientSharePage />} />
      <Route path="p/:slug" element={<PublicPortfolioPage />} />

      <Route element={<GuestOnly />}>
        <Route path="login" element={<LoginPage />} />
        <Route path="signup" element={<RegisterPage />} />
      </Route>

      <Route element={<RequireAuth />}>
        <Route index element={<EntryPage />} />
        <Route path="client" element={<ClientHome />} />
        <Route path="client/invite" element={<ClientInvitePage />} />
        <Route path="client/:section" element={<ClientServicePage />} />
        <Route path="client/projects/:projectId" element={<ClientServicePage />} />
        <Route path="client-profile" element={<ProfileEditor />} />
        <Route path="client-requests" element={<FreelancerInquiriesPage />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="contracts" element={<ContractsPage />} />
        <Route path="contracts/:contractId" element={<ContractDetailPage />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<ProjectDetailPage />} />
        <Route path="projects/:projectId/revise" element={<RevisionPage />} />
        <Route path="contracts/:contractId/project" element={<ContractProjectPage />} />
        <Route path="contracts/:contractId/analysis" element={<AnalysisPage />} />
        <Route path="invoices" element={<InvoicesPage />} />
        <Route path="invoices/new" element={<InvoiceFormPage />} />
        <Route path="invoices/:invoiceId" element={<InvoiceDetailPage />} />
        <Route path="invoices/:invoiceId/edit" element={<InvoiceFormPage />} />
        <Route path="settlement" element={<SettlementPage />} />
        <Route path="portfolio" element={<PortfolioPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  )
}
