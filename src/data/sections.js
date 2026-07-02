/*
 * Section + panel layout config. Each section is a tab; each panel names the
 * dataset(s) it renders and the chart form to use. Keeping this declarative
 * makes it trivial to add a metric: add a snapshot, (optionally) a fetcher,
 * then a panel entry here.
 */

export const SECTIONS = [
  {
    id: 'overview',
    label: 'Overview',
    title: 'The state of the planet, at a glance',
    blurb:
      'Headline signals across climate and nature, refreshed from public data. Use “Refresh” for the latest live values; anything without a live feed shows the most recent reference figure.',
  },
  {
    id: 'climate',
    label: 'Climate',
    title: 'Warming, greenhouse gases, ice & extremes',
    blurb:
      'The core physical indicators of a changing climate — temperature, the gases driving it, sea level and ice, the energy transition, and the extremes that follow.',
  },
  {
    id: 'business',
    label: 'Business & nature',
    title: 'Transition economics, climate risk & natural capital',
    blurb:
      'What the transition means for business: carbon pricing, clean-energy investment and costs, where emissions sit, physical & transition risk, and the state of the nature we depend on.',
  },
]

// Panels per section. `form` picks the chart component; `span` sets grid width.
export const PANELS = {
  climate: [
    { dataset: 'global-temperature', form: 'area', span: 8, upIsGood: false, decimals: 2 },
    { dataset: 'co2-concentration', form: 'line', span: 4, upIsGood: false, decimals: 1 },
    { dataset: 'co2-emissions', form: 'area', span: 4, upIsGood: false, decimals: 1 },
    { dataset: 'methane-concentration', form: 'line', span: 4, upIsGood: false, decimals: 0 },
    { dataset: 'sea-level', form: 'area', span: 4, upIsGood: false, decimals: 0 },
    { dataset: 'arctic-sea-ice', form: 'line', span: 6, upIsGood: true, decimals: 1 },
    { dataset: 'electricity-mix', form: 'stacked', span: 6, decimals: 1 },
    { dataset: 'disaster-events', form: 'bar', span: 12, upIsGood: false, decimals: 0 },
  ],
  business: [
    { dataset: 'carbon-price', form: 'area', span: 6, upIsGood: true, decimals: 0 },
    { dataset: 'transition-investment', form: 'bar', span: 6, upIsGood: true, decimals: 0 },
    { dataset: 'cleantech-costs', form: 'multiline', span: 8, logY: true, decimals: 0 },
    { dataset: 'net-zero-coverage', form: 'area', span: 4, upIsGood: true, decimals: 0 },
    { dataset: 'emissions-by-sector', form: 'hbar', span: 6, decimals: 1 },
    { dataset: 'catastrophe-losses', form: 'multiline', span: 6, upIsGood: false, decimals: 0 },
    { dataset: 'forest-loss', form: 'bar', span: 6, upIsGood: false, decimals: 1 },
    { dataset: 'living-planet-index', form: 'area', span: 6, upIsGood: true, decimals: 0 },
  ],
}

// Datasets surfaced as headline stat tiles on the Overview tab.
export const OVERVIEW_STATS = [
  { dataset: 'global-temperature', upIsGood: false, decimals: 2 },
  { dataset: 'co2-concentration', upIsGood: false, decimals: 1 },
  { dataset: 'co2-emissions', upIsGood: false, decimals: 1 },
  { dataset: 'sea-level', upIsGood: false, decimals: 0 },
  { dataset: 'arctic-sea-ice', upIsGood: true, decimals: 1 },
  { dataset: 'electricity-mix', upIsGood: true, decimals: 1, deriveKey: 'windSolar' },
  { dataset: 'carbon-price', upIsGood: true, decimals: 0 },
  { dataset: 'transition-investment', upIsGood: true, decimals: 0 },
  { dataset: 'living-planet-index', upIsGood: true, decimals: 0 },
]

// Which panels appear (compactly) on the Overview tab beneath the stat row.
export const OVERVIEW_PANELS = [
  { dataset: 'global-temperature', form: 'area', span: 6, upIsGood: false, decimals: 2 },
  { dataset: 'co2-concentration', form: 'line', span: 6, upIsGood: false, decimals: 1 },
  { dataset: 'electricity-mix', form: 'stacked', span: 6, decimals: 1 },
  { dataset: 'transition-investment', form: 'bar', span: 6, upIsGood: true, decimals: 0 },
]
