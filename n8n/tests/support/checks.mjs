import assert from 'node:assert/strict';

// A share passes within 4 standard errors of its expected value; an expected 0 must be exactly 0.
const STANDARD_ERRORS = 4;

// Assertions whose failure message names the seed that repeats the run.
export class Checks {
  constructor(random) {
    this.random = random;
  }

  fail(message) {
    return `${message}; repeat with ${this.random.repeat}`;
  }

  ok(label, condition) {
    assert.ok(condition, this.fail(label));
  }

  throws(label, run) {
    let threw = false;
    try {
      run();
    } catch {
      threw = true;
    }
    this.ok(label, threw);
  }

  share(label, actual, expected, count) {
    const tolerance = STANDARD_ERRORS * Math.sqrt((expected * (1 - expected)) / count);
    assert.ok(
      Math.abs(actual - expected) <= tolerance,
      this.fail(
        `${label}: ${actual.toFixed(3)} ` +
          `(expected ${expected.toFixed(3)} +- ${tolerance.toFixed(3)}, n ${count})`,
      ),
    );
  }
}
