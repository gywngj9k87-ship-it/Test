import { useMemo, useState } from 'react'
import { useClimateData, useAutoRefresh } from './hooks/useClimateData.js'
import { SECTIONS, PANELS, OVERVIEW_STATS, OVERVIEW_PANELS } from './data/sections.js'
import RefreshControls from './components/RefreshControls.jsx'
import StatusBar from './components/StatusBar.jsx'
import StatTile from './components/StatTile.jsx'
import Panel from './components/Panel.jsx'

export default function App() {
  const { datasets, refresh, isRefreshing, lastUpdated, snapshotAsOf } = useClimateData()
  const [activeSection, setActiveSection] = useState('overview')
  const [intervalSeconds, setIntervalSeconds] = useState(0)

  const autoOn = intervalSeconds > 0
  useAutoRefresh(refresh, autoOn, intervalSeconds || 300)

  const section = useMemo(
    () => SECTIONS.find((s) => s.id === activeSection) || SECTIONS[0],
    [activeSection],
  )

  return (
    <div className="app">
      <header className="header">
        <div className="header__row">
          <div className="brand">
            <div className="brand__mark" aria-hidden="true">◐</div>
            <div>
              <div className="brand__title">Terra Signals</div>
              <div className="brand__subtitle">Environment &amp; climate trends</div>
            </div>
          </div>
          <RefreshControls
            onRefresh={refresh}
            isRefreshing={isRefreshing}
            autoOn={autoOn}
            intervalSeconds={intervalSeconds || 300}
            onIntervalChange={setIntervalSeconds}
          />
        </div>
        <div className="container">
          <StatusBar
            datasets={datasets}
            lastUpdated={lastUpdated}
            isRefreshing={isRefreshing}
            snapshotAsOf={snapshotAsOf}
          />
          <nav className="tabs" aria-label="Sections">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                className={`tab ${activeSection === s.id ? 'tab--active' : ''}`}
                onClick={() => setActiveSection(s.id)}
              >
                {s.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="container" style={{ flex: 1 }}>
        <div className="section-intro">
          <h2>{section.title}</h2>
          <p>{section.blurb}</p>
        </div>

        {activeSection === 'overview' ? (
          <OverviewSection datasets={datasets} />
        ) : (
          <div className="grid">
            {(PANELS[activeSection] || []).map((cfg) => (
              <Panel key={cfg.dataset} dataset={datasets[cfg.dataset]} config={cfg} />
            ))}
          </div>
        )}
      </main>

      <footer className="footer">
        <div className="container">
          Terra Signals aggregates public climate &amp; environment data (NASA, NOAA,
          Ember, Global Carbon Project, IRENA, BloombergNEF, Swiss Re, WWF and others).
          Live values are fetched in your browser on refresh; where a live feed is
          unavailable, the most recent reference figure is shown. Figures are indicative
          — always cite the linked primary source for reporting.
        </div>
      </footer>
    </div>
  )
}

function OverviewSection({ datasets }) {
  return (
    <>
      <div className="stat-row" style={{ padding: '16px 0 8px' }}>
        {OVERVIEW_STATS.map((cfg) => (
          <StatTile
            key={`${cfg.dataset}-${cfg.deriveKey || ''}`}
            dataset={datasets[cfg.dataset]}
            upIsGood={cfg.upIsGood}
            decimals={cfg.decimals}
            deriveKey={cfg.deriveKey}
          />
        ))}
      </div>
      <div className="grid">
        {OVERVIEW_PANELS.map((cfg) => (
          <Panel key={cfg.dataset} dataset={datasets[cfg.dataset]} config={cfg} />
        ))}
      </div>
    </>
  )
}
