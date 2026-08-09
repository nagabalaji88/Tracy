import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import { Layout } from './Layout'
import { Overview } from './pages/Overview'
import { PromotionBoard } from './pages/PromotionBoard'
import { Explorer } from './pages/Explorer'
import { ForecastPage } from './pages/Forecast'
import { Simulator } from './pages/Simulator'
import { Breakers } from './pages/Breakers'
import { Framework } from './pages/Framework'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Overview />} />
          <Route path="/promotion" element={<PromotionBoard />} />
          <Route path="/explorer" element={<Explorer />} />
          <Route path="/forecast" element={<ForecastPage />} />
          <Route path="/simulator" element={<Simulator />} />
          <Route path="/breakers" element={<Breakers />} />
          <Route path="/framework" element={<Framework />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
