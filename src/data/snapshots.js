/*
 * Bundled cached snapshots — the offline fallback.
 *
 * Every dataset the platform shows has an authoritative series here, sourced
 * from public scientific records (NASA GISTEMP, NOAA GML, NSIDC, IEA/Ember,
 * BNEF, Swiss Re, WWF/Global Forest Watch, EU ETS). When a live fetch
 * succeeds it replaces `series` for that dataset; when it fails, this snapshot
 * is shown with a "cached" indicator so the dashboard always renders.
 *
 * Figures reflect full-year values through 2024 with early-2025 readings where
 * noted. They are intended as a credible baseline, not a substitute for the
 * live source — the "Refresh" button always attempts the live pull first.
 */

export const SNAPSHOT_AS_OF = '2025-06'

/* ------------------------------------------------------------------ *
 * CLIMATE — Temperature
 * ------------------------------------------------------------------ */

// NASA GISTEMP global surface temperature anomaly vs 1951–1980 mean (°C).
// 5-year steps to 1990, then annual. 2024 = warmest year on record.
export const globalTemperature = {
  id: 'global-temperature',
  title: 'Global temperature anomaly',
  unit: '°C',
  baseline: 'vs 1951–1980 average',
  sourceName: 'NASA GISTEMP v4',
  sourceUrl: 'https://data.giss.nasa.gov/gistemp/',
  series: [
    { year: 1880, value: -0.16 }, { year: 1890, value: -0.35 },
    { year: 1900, value: -0.09 }, { year: 1910, value: -0.43 },
    { year: 1920, value: -0.28 }, { year: 1930, value: -0.14 },
    { year: 1940, value: 0.12 }, { year: 1950, value: -0.17 },
    { year: 1960, value: -0.03 }, { year: 1970, value: 0.03 },
    { year: 1980, value: 0.27 }, { year: 1985, value: 0.1 },
    { year: 1990, value: 0.45 }, { year: 1995, value: 0.45 },
    { year: 2000, value: 0.41 }, { year: 2005, value: 0.69 },
    { year: 2010, value: 0.72 }, { year: 2014, value: 0.75 },
    { year: 2015, value: 0.9 }, { year: 2016, value: 1.02 },
    { year: 2017, value: 0.93 }, { year: 2018, value: 0.85 },
    { year: 2019, value: 0.99 }, { year: 2020, value: 1.02 },
    { year: 2021, value: 0.85 }, { year: 2022, value: 0.9 },
    { year: 2023, value: 1.17 }, { year: 2024, value: 1.28 },
  ],
  note: '2024 was the warmest year in the 145-year record — about 1.47 °C above the 1850–1900 pre-industrial baseline, the first calendar year near the Paris 1.5 °C guardrail.',
}

/* ------------------------------------------------------------------ *
 * CLIMATE — Greenhouse gases
 * ------------------------------------------------------------------ */

// NOAA GML Mauna Loa annual mean CO2 (ppm).
export const co2Concentration = {
  id: 'co2-concentration',
  title: 'Atmospheric CO₂',
  unit: 'ppm',
  baseline: 'Mauna Loa annual mean',
  sourceName: 'NOAA Global Monitoring Laboratory',
  sourceUrl: 'https://gml.noaa.gov/ccgg/trends/',
  series: [
    { year: 1960, value: 316.9 }, { year: 1965, value: 320.0 },
    { year: 1970, value: 325.7 }, { year: 1975, value: 331.1 },
    { year: 1980, value: 338.8 }, { year: 1985, value: 346.1 },
    { year: 1990, value: 354.4 }, { year: 1995, value: 360.8 },
    { year: 2000, value: 369.7 }, { year: 2005, value: 379.8 },
    { year: 2010, value: 389.9 }, { year: 2015, value: 400.8 },
    { year: 2018, value: 408.5 }, { year: 2019, value: 411.7 },
    { year: 2020, value: 414.2 }, { year: 2021, value: 416.5 },
    { year: 2022, value: 418.6 }, { year: 2023, value: 421.1 },
    { year: 2024, value: 424.6 }, { year: 2025, value: 427.3 },
  ],
  note: 'CO₂ is now ~50% above its pre-industrial level of 280 ppm. The May 2025 monthly peak topped 430 ppm — the highest in at least 800,000 years of ice-core record.',
}

// NOAA GML global mean atmospheric methane (ppb).
export const methaneConcentration = {
  id: 'methane-concentration',
  title: 'Atmospheric methane (CH₄)',
  unit: 'ppb',
  baseline: 'Global monthly mean',
  sourceName: 'NOAA Global Monitoring Laboratory',
  sourceUrl: 'https://gml.noaa.gov/ccgg/trends_ch4/',
  series: [
    { year: 1985, value: 1620 }, { year: 1990, value: 1714 },
    { year: 1995, value: 1749 }, { year: 2000, value: 1773 },
    { year: 2005, value: 1774 }, { year: 2010, value: 1799 },
    { year: 2015, value: 1834 }, { year: 2018, value: 1857 },
    { year: 2020, value: 1879 }, { year: 2021, value: 1896 },
    { year: 2022, value: 1911 }, { year: 2023, value: 1922 },
    { year: 2024, value: 1930 },
  ],
  note: 'Methane is ~160% above pre-industrial levels and has accelerated since 2007. It is ~80× more potent than CO₂ over a 20-year horizon.',
}

// Global fossil-fuel & industry CO2 emissions (Gt CO2/yr), Global Carbon Project.
export const co2Emissions = {
  id: 'co2-emissions',
  title: 'Global CO₂ emissions',
  unit: 'Gt/yr',
  baseline: 'Fossil fuels & industry',
  sourceName: 'Global Carbon Project',
  sourceUrl: 'https://globalcarbonproject.org/',
  series: [
    { year: 1960, value: 9.4 }, { year: 1970, value: 14.9 },
    { year: 1980, value: 19.5 }, { year: 1990, value: 22.7 },
    { year: 1995, value: 23.5 }, { year: 2000, value: 25.5 },
    { year: 2005, value: 29.9 }, { year: 2010, value: 33.3 },
    { year: 2015, value: 35.5 }, { year: 2019, value: 37.1 },
    { year: 2020, value: 35.3 }, { year: 2021, value: 37.1 },
    { year: 2022, value: 37.4 }, { year: 2023, value: 37.8 },
    { year: 2024, value: 37.8 },
  ],
  note: 'Fossil CO₂ emissions hit a record ~37.8 Gt in 2024. Including land-use change, total emissions are near 41 Gt — still rising when they must fall ~45% by 2030 for a 1.5 °C path.',
}

/* ------------------------------------------------------------------ *
 * CLIMATE — Sea level & ice
 * ------------------------------------------------------------------ */

// Global mean sea level, satellite altimetry, cumulative rise since 1993 (mm).
export const seaLevel = {
  id: 'sea-level',
  title: 'Global mean sea level',
  unit: 'mm',
  baseline: 'Rise since 1993',
  sourceName: 'NASA / Satellite altimetry',
  sourceUrl: 'https://climate.nasa.gov/vital-signs/sea-level/',
  series: [
    { year: 1993, value: 0 }, { year: 1996, value: 9 },
    { year: 1999, value: 19 }, { year: 2002, value: 28 },
    { year: 2005, value: 38 }, { year: 2008, value: 45 },
    { year: 2011, value: 55 }, { year: 2014, value: 66 },
    { year: 2017, value: 83 }, { year: 2020, value: 95 },
    { year: 2022, value: 101 }, { year: 2023, value: 106 },
    { year: 2024, value: 111 },
  ],
  note: 'Seas have risen ~111 mm since 1993 and the rate has more than doubled — from ~2.1 mm/yr in the 1990s to ~4.5 mm/yr today — as ice sheets and warming oceans dominate.',
}

// Arctic sea-ice September minimum extent (million km²), NSIDC.
export const arcticSeaIce = {
  id: 'arctic-sea-ice',
  title: 'Arctic sea-ice minimum',
  unit: 'M km²',
  baseline: 'September extent',
  sourceName: 'NSIDC',
  sourceUrl: 'https://nsidc.org/arcticseaicenews/',
  series: [
    { year: 1980, value: 7.7 }, { year: 1985, value: 6.9 },
    { year: 1990, value: 6.2 }, { year: 1995, value: 6.1 },
    { year: 2000, value: 6.3 }, { year: 2005, value: 5.6 },
    { year: 2007, value: 4.3 }, { year: 2010, value: 4.9 },
    { year: 2012, value: 3.6 }, { year: 2015, value: 4.6 },
    { year: 2018, value: 4.7 }, { year: 2020, value: 3.9 },
    { year: 2021, value: 4.9 }, { year: 2022, value: 4.9 },
    { year: 2023, value: 4.4 }, { year: 2024, value: 4.3 },
  ],
  note: 'The Arctic has lost roughly 40% of its summer sea ice since 1980. The record low was September 2012 at 3.6 M km²; recent years cluster well below the 1980s norm.',
}

/* ------------------------------------------------------------------ *
 * CLIMATE — Energy & extremes
 * ------------------------------------------------------------------ */

// Share of global electricity generation by source (%), Ember / IEA.
export const electricityMix = {
  id: 'electricity-mix',
  title: 'Global electricity mix',
  unit: '% of generation',
  baseline: 'Share by source',
  sourceName: 'Ember',
  sourceUrl: 'https://ember-energy.org/',
  keys: [
    { key: 'fossil', label: 'Fossil fuels', series: 'series-6' },
    { key: 'nuclearHydro', label: 'Nuclear & hydro', series: 'series-1' },
    { key: 'windSolar', label: 'Wind & solar', series: 'series-2' },
    { key: 'otherRenew', label: 'Other renewables', series: 'series-3' },
  ],
  series: [
    { year: 2000, fossil: 65.2, nuclearHydro: 33.4, windSolar: 0.2, otherRenew: 1.2 },
    { year: 2005, fossil: 67.0, nuclearHydro: 30.0, windSolar: 0.6, otherRenew: 1.4 },
    { year: 2010, fossil: 67.1, nuclearHydro: 29.0, windSolar: 1.7, otherRenew: 2.2 },
    { year: 2015, fossil: 66.3, nuclearHydro: 26.0, windSolar: 4.6, otherRenew: 3.1 },
    { year: 2018, fossil: 64.3, nuclearHydro: 25.0, windSolar: 7.2, otherRenew: 3.5 },
    { year: 2020, fossil: 61.3, nuclearHydro: 25.4, windSolar: 9.3, otherRenew: 4.0 },
    { year: 2021, fossil: 62.0, nuclearHydro: 24.4, windSolar: 10.2, otherRenew: 3.4 },
    { year: 2022, fossil: 60.8, nuclearHydro: 24.2, windSolar: 12.0, otherRenew: 3.0 },
    { year: 2023, fossil: 60.4, nuclearHydro: 23.5, windSolar: 13.4, otherRenew: 2.7 },
    { year: 2024, fossil: 58.5, nuclearHydro: 23.5, windSolar: 15.0, otherRenew: 3.0 },
  ],
  note: 'Wind and solar supplied a record ~15% of global electricity in 2024, up from under 2% in 2010. Fossil generation is plateauing as clean sources meet most new demand.',
}

// Recorded weather/climate-related disaster events per year, EM-DAT.
export const disasterEvents = {
  id: 'disaster-events',
  title: 'Climate-related disasters',
  unit: 'events/yr',
  baseline: 'Recorded weather & climate events',
  sourceName: 'EM-DAT (CRED)',
  sourceUrl: 'https://www.emdat.be/',
  series: [
    { year: 1980, value: 130 }, { year: 1985, value: 180 },
    { year: 1990, value: 240 }, { year: 1995, value: 290 },
    { year: 2000, value: 345 }, { year: 2005, value: 370 },
    { year: 2010, value: 385 }, { year: 2015, value: 375 },
    { year: 2018, value: 340 }, { year: 2020, value: 405 },
    { year: 2021, value: 380 }, { year: 2022, value: 387 },
    { year: 2023, value: 399 },
  ],
  note: 'Recorded climate-related disasters have roughly tripled since 1980. Some rise reflects better reporting, but the trend in floods, storms and heatwaves is real and accelerating.',
}

/* ------------------------------------------------------------------ *
 * BUSINESS — Carbon markets & pricing
 * ------------------------------------------------------------------ */

// EU ETS carbon allowance price (EUR / t CO2), annual average.
export const carbonPrice = {
  id: 'carbon-price',
  title: 'EU ETS carbon price',
  unit: '€/t',
  baseline: 'Annual average allowance price',
  sourceName: 'EU Emissions Trading System',
  sourceUrl: 'https://ember-energy.org/data/carbon-price-viewer/',
  series: [
    { year: 2013, value: 4.5 }, { year: 2015, value: 7.7 },
    { year: 2017, value: 5.8 }, { year: 2018, value: 16 },
    { year: 2019, value: 25 }, { year: 2020, value: 25 },
    { year: 2021, value: 54 }, { year: 2022, value: 81 },
    { year: 2023, value: 84 }, { year: 2024, value: 65 },
    { year: 2025, value: 72 },
  ],
  note: 'Europe’s carbon price rose from single digits to ~€80 as the cap tightened, peaking near €100 in early 2023. It underpins the business case for industrial decarbonisation across the EU.',
}

/* ------------------------------------------------------------------ *
 * BUSINESS — Renewable investment & costs
 * ------------------------------------------------------------------ */

// Global energy-transition investment (US$ billion/yr), BloombergNEF.
export const transitionInvestment = {
  id: 'transition-investment',
  title: 'Energy-transition investment',
  unit: '$bn/yr',
  baseline: 'Global, all sectors',
  sourceName: 'BloombergNEF',
  sourceUrl: 'https://about.bnef.com/',
  series: [
    { year: 2015, value: 350 }, { year: 2017, value: 400 },
    { year: 2019, value: 460 }, { year: 2020, value: 530 },
    { year: 2021, value: 750 }, { year: 2022, value: 1130 },
    { year: 2023, value: 1770 }, { year: 2024, value: 2080 },
  ],
  note: 'Global investment in the energy transition topped $2 trillion in 2024 — now roughly on par with, and in clean power exceeding, new fossil-fuel supply spending.',
}

// Levelised cost / price declines, indexed technologies.
export const cleanTechCosts = {
  id: 'cleantech-costs',
  title: 'Falling clean-tech costs',
  unit: '$',
  baseline: 'Cost per unit (log-scale decline)',
  sourceName: 'IRENA / BloombergNEF',
  sourceUrl: 'https://www.irena.org/Data',
  keys: [
    { key: 'solar', label: 'Solar PV (LCOE, $/MWh)', series: 'series-3' },
    { key: 'windOnshore', label: 'Onshore wind (LCOE, $/MWh)', series: 'series-2' },
    { key: 'battery', label: 'Battery pack ($/kWh)', series: 'series-1' },
  ],
  series: [
    { year: 2010, solar: 378, windOnshore: 100, battery: 1200 },
    { year: 2013, solar: 250, windOnshore: 88, battery: 668 },
    { year: 2015, solar: 180, windOnshore: 70, battery: 384 },
    { year: 2017, solar: 100, windOnshore: 60, battery: 209 },
    { year: 2019, solar: 68, windOnshore: 53, battery: 156 },
    { year: 2021, solar: 45, windOnshore: 39, battery: 132 },
    { year: 2023, solar: 40, windOnshore: 33, battery: 139 },
    { year: 2024, solar: 38, windOnshore: 33, battery: 115 },
  ],
  note: 'Solar electricity is ~90% cheaper than in 2010 and battery packs ~90% cheaper than in 2013. These learning curves — not policy alone — now drive the transition’s economics.',
}

/* ------------------------------------------------------------------ *
 * BUSINESS — Corporate & sector emissions / ESG
 * ------------------------------------------------------------------ */

// Global GHG emissions by sector (% share), Climate Watch / WRI.
export const emissionsBySector = {
  id: 'emissions-by-sector',
  title: 'Global emissions by sector',
  unit: '% of GHG',
  baseline: 'Share of total greenhouse gases',
  sourceName: 'Climate Watch / WRI',
  sourceUrl: 'https://www.climatewatchdata.org/',
  series: [
    { sector: 'Electricity & heat', value: 31.9 },
    { sector: 'Transport', value: 14.3 },
    { sector: 'Manufacturing & construction', value: 12.7 },
    { sector: 'Agriculture', value: 11.6 },
    { sector: 'Land-use change & forestry', value: 6.5 },
    { sector: 'Fugitive emissions', value: 5.8 },
    { sector: 'Buildings', value: 5.6 },
    { sector: 'Industrial processes', value: 5.2 },
    { sector: 'Other fuel combustion', value: 3.1 },
    { sector: 'Waste', value: 3.3 },
  ],
  note: 'Energy — power, transport, industry and buildings — drives roughly three-quarters of emissions, making it the primary lever for corporate decarbonisation and Scope 1–3 accounting.',
}

// Share of global emissions covered by net-zero targets (%), Net Zero Tracker.
export const netZeroCoverage = {
  id: 'net-zero-coverage',
  title: 'Net-zero target coverage',
  unit: '% of emissions',
  baseline: 'Global emissions under a net-zero pledge',
  sourceName: 'Net Zero Tracker',
  sourceUrl: 'https://zerotracker.net/',
  series: [
    { year: 2019, value: 16 }, { year: 2020, value: 50 },
    { year: 2021, value: 68 }, { year: 2022, value: 83 },
    { year: 2023, value: 88 }, { year: 2024, value: 89 },
  ],
  note: 'Nearly 90% of global emissions are now covered by a net-zero pledge from a country, region or major company — though credibility and interim targets vary widely.',
}

/* ------------------------------------------------------------------ *
 * BUSINESS — Climate risk exposure
 * ------------------------------------------------------------------ */

// Natural-catastrophe losses (US$ billion/yr), Swiss Re / Munich Re.
export const catastropheLosses = {
  id: 'catastrophe-losses',
  title: 'Natural-catastrophe losses',
  unit: '$bn/yr',
  baseline: 'Total vs insured (weather & climate)',
  sourceName: 'Swiss Re Institute',
  sourceUrl: 'https://www.swissre.com/institute/',
  keys: [
    { key: 'total', label: 'Total economic losses', series: 'series-6' },
    { key: 'insured', label: 'Insured losses', series: 'series-1' },
  ],
  series: [
    { year: 2016, total: 175, insured: 54 },
    { year: 2017, total: 350, insured: 150 },
    { year: 2018, total: 175, insured: 90 },
    { year: 2019, total: 150, insured: 60 },
    { year: 2020, total: 210, insured: 89 },
    { year: 2021, total: 280, insured: 130 },
    { year: 2022, total: 275, insured: 132 },
    { year: 2023, total: 280, insured: 118 },
    { year: 2024, total: 320, insured: 140 },
  ],
  note: 'Weather-driven losses now routinely exceed $250 bn a year, and less than half is insured. The widening "protection gap" is reshaping insurance, lending and real-asset risk.',
}

/* ------------------------------------------------------------------ *
 * BUSINESS — Nature risk & natural capital
 * ------------------------------------------------------------------ */

// Global tree-cover loss (million hectares/yr), Global Forest Watch.
export const forestLoss = {
  id: 'forest-loss',
  title: 'Global tree-cover loss',
  unit: 'Mha/yr',
  baseline: 'Annual loss',
  sourceName: 'Global Forest Watch',
  sourceUrl: 'https://www.globalforestwatch.org/',
  series: [
    { year: 2015, value: 20.0 }, { year: 2016, value: 29.4 },
    { year: 2017, value: 29.4 }, { year: 2018, value: 24.5 },
    { year: 2019, value: 24.2 }, { year: 2020, value: 25.8 },
    { year: 2021, value: 25.3 }, { year: 2022, value: 22.8 },
    { year: 2023, value: 28.3 }, { year: 2024, value: 30.0 },
  ],
  note: 'The world lost ~30 Mha of tree cover in 2024, with fire-driven losses at record highs. Deforestation exposure is now a material supply-chain and disclosure risk (TNFD, EUDR).',
}

// WWF Living Planet Index — average wildlife population size, 1970 = 100.
export const livingPlanetIndex = {
  id: 'living-planet-index',
  title: 'Living Planet Index',
  unit: 'index (1970 = 100)',
  baseline: 'Average monitored wildlife populations',
  sourceName: 'WWF / ZSL',
  sourceUrl: 'https://www.livingplanetindex.org/',
  series: [
    { year: 1970, value: 100 }, { year: 1980, value: 82 },
    { year: 1990, value: 63 }, { year: 2000, value: 52 },
    { year: 2010, value: 40 }, { year: 2016, value: 34 },
    { year: 2018, value: 32 }, { year: 2020, value: 27 },
  ],
  note: 'Monitored wildlife populations have declined an average 73% since 1970. Over half of global GDP depends moderately or highly on nature, putting biodiversity squarely on the balance sheet.',
}

/* ------------------------------------------------------------------ */

export const SNAPSHOTS = {
  'global-temperature': globalTemperature,
  'co2-concentration': co2Concentration,
  'methane-concentration': methaneConcentration,
  'co2-emissions': co2Emissions,
  'sea-level': seaLevel,
  'arctic-sea-ice': arcticSeaIce,
  'electricity-mix': electricityMix,
  'disaster-events': disasterEvents,
  'carbon-price': carbonPrice,
  'transition-investment': transitionInvestment,
  'cleantech-costs': cleanTechCosts,
  'emissions-by-sector': emissionsBySector,
  'net-zero-coverage': netZeroCoverage,
  'catastrophe-losses': catastropheLosses,
  'forest-loss': forestLoss,
  'living-planet-index': livingPlanetIndex,
}
