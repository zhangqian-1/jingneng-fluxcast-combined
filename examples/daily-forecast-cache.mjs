// Platform integration example. Persist the returned cache in the platform DB
// or localStorage; a response without daily points must not erase this cache.
const DAY_MS = 24 * 60 * 60 * 1000;
const STEP_MS = 15 * 60 * 1000;
const OFFSET_MS = 8 * 60 * 60 * 1000;

export function beijingDay(now = new Date()) {
  return new Date(now.getTime() + OFFSET_MS).toISOString().slice(0, 10);
}

function parseUtc(timestamp) {
  if (typeof timestamp !== 'string' || !/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:?00)?$/.test(timestamp)) {
    throw new Error('Expected the agreed UTC timestamp');
  }
  const text = timestamp.replace(' ', 'T');
  const value = Date.parse(/(?:Z|\+00:?00)$/.test(text) ? text : text + 'Z');
  if (!Number.isFinite(value)) throw new Error('Invalid timestamp');
  return value;
}

export function mergeDailyForecast(cache, response) {
  const incoming = (response.result_point ?? []).filter(
    point => point.varname === 'totalPowerForecastDayAhead',
  );
  if (incoming.length === 0) return cache;
  if (incoming.length !== 96) throw new Error('Keep existing curve: incomplete daily batch');
  const points = incoming.map(point => ({...point, instant: parseUtc(point.timestamp)}))
    .sort((a, b) => a.instant - b.instant);
  const day = beijingDay(new Date(points[0].instant));
  const midnight = Date.parse(day + 'T00:00:00+08:00');
  points.forEach((point, i) => {
    if (point.instant !== midnight + i * STEP_MS ||
        typeof point.value !== 'number' || !Number.isFinite(point.value) || point.value < 0) {
      throw new Error('Keep existing curve: invalid daily axis or value');
    }
  });
  if (points[95].instant + STEP_MS !== midnight + DAY_MS) throw new Error('Invalid day end');
  return {...cache, [day]: points.map(({instant, ...point}) => point)};
}

export function currentDayCurve(cache, now = new Date()) {
  // Yesterday's curve remains in history but must never be displayed as today's.
  return cache[beijingDay(now)] ?? [];
}
