// Turning forecast occupancy into the number a manager acts on: staff per hour.
//
// Staff needed in an hour = ceil(90th-percentile occupancy in that hour / customers one member of
// staff can serve), never below a floor of two to open. The comparison roster is what businesses
// told the council they do today: staff for the expected peak, all day.

export const WAGE_GBP = 12.71; // UK National Living Wage (21+) from April 2026; set per business
export const MIN_STAFF = 2;

function quantile(values, q) {
  if (!values.length) return 0;
  const s = [...values].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(q * s.length))];
}

// series: occupancy per minute starting at `start` (seconds since midnight).
export function hourlyStaff(venue, series, start, upToMinute = series.length) {
  const out = [];
  const firstHour = Math.floor(start / 3600);
  const offset = (start / 60) % 60; // minutes into the first hour
  const hours = Math.ceil((series.length + offset) / 60);
  for (let h = 0; h < hours; h++) {
    const lo = Math.max(0, Math.round(h * 60 - offset));
    const hi = Math.min(series.length, upToMinute, Math.round((h + 1) * 60 - offset));
    if (hi <= lo) {
      out.push({ hour: firstHour + h, p90: 0, peak: 0, staff: null });
      continue;
    }
    const slice = Array.from(series.slice(lo, hi));
    const p90 = quantile(slice, 0.9);
    const staff = venue.perStaff ? Math.max(MIN_STAFF, Math.ceil(p90 / venue.perStaff)) : 0;
    out.push({ hour: firstHour + h, p90, peak: Math.max(...slice), staff });
  }
  return out;
}

export function compareRosters(hours) {
  const known = hours.filter((h) => h.staff !== null);
  const flat = known.length ? Math.max(...known.map((h) => h.staff)) : 0;
  const forecastHours = known.reduce((s, h) => s + h.staff, 0);
  const flatHours = flat * known.length;
  return {
    flat,
    forecastHours,
    flatHours,
    savedHours: flatHours - forecastHours,
    savedGBP: (flatHours - forecastHours) * WAGE_GBP,
  };
}
