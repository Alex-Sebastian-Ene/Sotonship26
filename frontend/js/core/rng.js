// Seeded randomness so every simulation run (and every replay the backend sends) is repeatable.

export function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class Rng {
  constructor(seed = 26) {
    this.seed = seed;
    this.next = mulberry32(seed);
  }

  uniform(lo = 0, hi = 1) {
    return lo + (hi - lo) * this.next();
  }

  normal(mean = 0, sd = 1) {
    const u = Math.max(this.next(), 1e-12);
    const v = this.next();
    return mean + sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
  }

  // Gamma via Marsaglia-Tsang; used for Beta draws below.
  gamma(k) {
    if (k < 1) return this.gamma(k + 1) * Math.pow(this.next(), 1 / k);
    const d = k - 1 / 3;
    const c = 1 / Math.sqrt(9 * d);
    for (;;) {
      let x;
      let v;
      do {
        x = this.normal();
        v = 1 + c * x;
      } while (v <= 0);
      v = v * v * v;
      const u = this.next();
      if (u < 1 - 0.0331 * x ** 4) return d * v;
      if (Math.log(u) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v;
    }
  }

  beta(a, b) {
    const x = this.gamma(a);
    return x / (x + this.gamma(b));
  }

  lognormal(median, sigma) {
    return median * Math.exp(this.normal(0, sigma));
  }

  pick(items) {
    return items[Math.floor(this.next() * items.length)];
  }

  // Index drawn from unnormalised weights.
  weighted(weights) {
    let total = 0;
    for (const w of weights) total += w;
    let r = this.next() * total;
    for (let i = 0; i < weights.length; i++) {
      r -= weights[i];
      if (r <= 0) return i;
    }
    return weights.length - 1;
  }

  binomial(n, p) {
    if (n < 60) {
      let k = 0;
      for (let i = 0; i < n; i++) if (this.next() < p) k++;
      return k;
    }
    const mean = n * p;
    const sd = Math.sqrt(n * p * (1 - p));
    return Math.max(0, Math.min(n, Math.round(this.normal(mean, sd))));
  }
}
