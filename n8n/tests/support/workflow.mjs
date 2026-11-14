import { readFileSync } from 'node:fs';
import vm from 'node:vm';

// One Code node from the workflow JSON, run in its own context on a simulated clock, with
// Math.random from the given seeded stream.
export class CodeNode {
  constructor(entry, random, defaultNow) {
    // n8n runs a Code node's source as a function body, so a top-level return is allowed.
    this.script = new vm.Script(`(() => {\n${entry.parameters.jsCode}\n})()`, {
      filename: entry.name,
    });
    this.defaultNow = defaultNow;
    const clock = { now: 0 };
    class ClockDate extends Date {
      constructor(...args) {
        super(...(args.length > 0 ? args : [clock.now]));
      }

      static now() {
        return clock.now;
      }
    }
    this.clock = clock;
    this.context = vm.createContext({
      Date: ClockDate,
      Math: Object.create(Math, { random: { value: random } }),
    });
  }

  // `input` is the node's items, `nodes` the items of earlier nodes the code reads with $('name').
  run({ now = this.defaultNow, input = [], nodes = {} }) {
    const items = (list) => ({ first: () => list[0], all: () => list });
    this.clock.now = now;
    this.context.$input = items(input.map((json) => ({ json })));
    this.context.$ = (name) => {
      if (!nodes[name]) {
        throw new Error(`Node '${name}' hasn't been executed`);
      }
      return items(nodes[name].map((json) => ({ json })));
    };
    return [...this.script.runInContext(this.context)].map((item) => item.json);
  }
}

// A workflow file from n8n/workflows/, with its Code nodes ready to run.
export class Workflow {
  constructor(file, { random, now = 0 }) {
    this.json = JSON.parse(
      readFileSync(new URL(`../../workflows/${file}`, import.meta.url), 'utf8'),
    );
    this.random = random;
    this.now = now;
    this.entries = new Map(this.json.nodes.map((entry) => [entry.name, entry]));
    this.codeNodes = new Map();
  }

  entry(name) {
    const entry = this.entries.get(name);
    if (!entry) {
      throw new Error(`No node named ${name} in the workflow`);
    }
    return entry;
  }

  codeNode(name) {
    if (!this.codeNodes.has(name)) {
      this.codeNodes.set(name, new CodeNode(this.entry(name), this.random, this.now));
    }
    return this.codeNodes.get(name);
  }
}
