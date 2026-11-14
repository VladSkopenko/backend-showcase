// mulberry32: one seeded stream for a test file and every Code node it runs, so a seed repeats a
// run. The seed comes from the given environment variable, or a random one when it is unset.
export class SeededRandom {
  constructor(variable) {
    this.variable = variable;
    this.seed = Number(process.env[variable] ?? Math.floor(Math.random() * 2 ** 32));
    this.state = this.seed >>> 0;
    this.next = this.next.bind(this);
  }

  next() {
    this.state = (this.state + 0x6d2b79f5) >>> 0;
    let value = this.state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 2 ** 32;
  }

  get repeat() {
    return `${this.variable}=${this.seed}`;
  }
}

// Draws a test queues up front, in the order the Code nodes take them; once they run out, the
// seeded stream takes over.
export class ForcedDraws {
  constructor(random) {
    this.queue = [];
    this.next = () => (this.queue.length > 0 ? this.queue.shift() : random());
  }

  push(...draws) {
    this.queue.push(...draws);
  }

  replace(draws) {
    this.queue.length = 0;
    this.queue.push(...draws);
  }

  get left() {
    return this.queue.length;
  }
}
