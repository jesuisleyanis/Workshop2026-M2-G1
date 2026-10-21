import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { BeneficiariesPage } from './pages/BeneficiariesPage'
import { HistoryPage } from './pages/HistoryPage'
import { LimitsPage } from './pages/LimitsPage'
import { HomePage } from './pages/HomePage'
import { LoginPage } from './pages/LoginPage'
import { ProfilePage } from './pages/ProfilePage'
import { RibPage } from './pages/RibPage'
import { SendPage } from './pages/SendPage'
import { StatsPage } from './pages/StatsPage'
import { TxDetailPage } from './pages/TxDetailPage'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="stats" element={<StatsPage />} />
          <Route path="send" element={<SendPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="operations/:id" element={<TxDetailPage />} />
          <Route path="rib" element={<RibPage />} />
          <Route path="beneficiaries" element={<BeneficiariesPage />} />
          <Route path="limits" element={<LimitsPage />} />
          <Route path="profile" element={<ProfilePage />} />
          {/* Anciennes routes (liens existants, scripts de démo). */}
          <Route path="transfer" element={<Navigate to="/send" replace />} />
          <Route path="accounts" element={<Navigate to="/rib" replace />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
