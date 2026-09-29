import assert from 'node:assert/strict';
import {mergeDailyForecast, currentDayCurve} from '../examples/daily-forecast-cache.mjs';

const midnight = Date.parse('2026-09-29T00:00:00+08:00');
const points = Array.from({length: 96}, (_, i) => ({
  varname: 'totalPowerForecastDayAhead',
  timestamp: new Date(midnight + i * 900000).toISOString().slice(0, 19).replace('T', ' '),
  value: 1000 + i,
}));
const today = new Date('2026-09-29T12:00:00+08:00');
const cache = mergeDailyForecast({}, {result_point: [...points].reverse()});
assert.deepEqual(currentDayCurve(cache, today), points);
assert.equal(mergeDailyForecast(cache, {result_point: [{varname: 'totalPowerForecast', value: 500}]}), cache);
assert.deepEqual(mergeDailyForecast(cache, {result_point: points}), cache);
assert.deepEqual(currentDayCurve(cache, new Date('2026-09-30T00:00:00+08:00')), []);
assert.deepEqual(currentDayCurve(JSON.parse(JSON.stringify(cache)), today), points);
assert.throws(() => mergeDailyForecast(cache, {result_point: points.slice(1)}));
assert.throws(() => mergeDailyForecast(cache, {result_point: [points[0], ...points.slice(0, 95)]}));
assert.throws(() => mergeDailyForecast(cache, {result_point: [{...points[0], value: null}, ...points.slice(1)]}));
assert.deepEqual(currentDayCurve(cache, today), points);
console.log(JSON.stringify({passed: true, checks: 9, platform_deployed: false}));
