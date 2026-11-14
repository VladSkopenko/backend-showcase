import vm from 'node:vm';

import { DEV_API } from './constants.mjs';

// n8n expressions in the HTTP nodes: `={{ ... }}` parts evaluated against the item.
const render = (template, json) =>
  template.startsWith('=')
    ? template
        .slice(1)
        .replace(/\{\{(.*?)\}\}/g, (_, expression) =>
          String(vm.runInNewContext(expression, { $json: json, JSON })),
        )
    : template;

// One HTTP Request node call for one item, the way n8n sends it: query, headers, JSON body and the
// custom auth credential's name. Without neverError a non-2xx answer fails the node.
const callHttp = (node, item, api) => {
  const parameters = node.parameters;
  const query = parameters.sendQuery
    ? parameters.queryParameters.parameters
        .map(({ name, value }) => `${name}=${render(value, item)}`)
        .join('&')
    : '';
  const answer = api({
    method: parameters.method ?? 'GET',
    url: render(parameters.url, item) + (query ? `?${query}` : ''),
    headers: Object.fromEntries(
      (parameters.sendHeaders ? parameters.headerParameters.parameters : []).map(
        ({ name, value }) => [name, render(value, item)],
      ),
    ),
    body: parameters.sendBody ? JSON.parse(render(parameters.jsonBody, item)) : undefined,
    credential: node.credentials?.httpCustomAuth?.name,
  });
  const response = parameters.options?.response?.response ?? {};
  if (!response.neverError && (answer.statusCode < 200 || answer.statusCode > 299)) {
    throw new Error(`${node.name} answered ${answer.statusCode}`);
  }
  return response.fullResponse
    ? { statusCode: answer.statusCode, body: answer.body, headers: answer.headers ?? {} }
    : answer.body;
};

// Runs a workflow from its trigger along its connections: Code nodes from the JSON, HTTP nodes
// against a stub API, the Loop Over Items node as n8n's v3 does it (one batch per pass, `done` once
// the items run out). The Code nodes draw from `forced` first.
export class WorkflowEmulator {
  constructor(workflow, forced) {
    this.workflow = workflow;
    this.forced = forced;
  }

  // Returns the API calls made, the error that failed the run, whether every loop reached `done`
  // and how many forced draws were left untaken.
  execute({ api, randoms = [], now = this.workflow.now }) {
    const { json } = this.workflow;
    this.forced.replace(randoms);
    const outputs = {};
    const loops = new Map();
    const calls = [];
    const logged = (request) => {
      calls.push(`${request.method} ${request.url.replace(DEV_API, '')}`);
      return api(request);
    };
    const loop = (node, input) => {
      const batchSize = node.parameters.batchSize ?? 1;
      const state = loops.get(node.name);
      if (!state) {
        loops.set(node.name, { pending: input.slice(batchSize), processed: [], done: false });
        return [[], input.slice(0, batchSize)];
      }
      state.processed.push(...input);
      if (state.pending.length === 0) {
        state.done = true;
        return [state.processed, []];
      }
      return [[], state.pending.splice(0, batchSize)];
    };
    const runNode = (name, input) => {
      const node = this.workflow.entry(name);
      let out;
      switch (node.type) {
        case 'n8n-nodes-base.scheduleTrigger':
          out = [[{}]];
          break;
        case 'n8n-nodes-base.code':
          out = [this.workflow.codeNode(name).run({ now, input, nodes: outputs })];
          break;
        case 'n8n-nodes-base.httpRequest':
          out = [input.map((item) => callHttp(node, item, logged))];
          break;
        case 'n8n-nodes-base.splitInBatches':
          out = loop(node, input);
          break;
        default:
          throw new Error(`The check cannot run a ${node.type} node (${name})`);
      }
      outputs[name] = out[0];
      (json.connections[name]?.main ?? []).forEach((targets, index) => {
        const items = out[index] ?? [];
        if (items.length > 0) {
          for (const { node: target } of targets ?? []) {
            runNode(target, items);
          }
        }
      });
    };
    const trigger = json.nodes.find((entry) => entry.type === 'n8n-nodes-base.scheduleTrigger');
    let error = null;
    try {
      runNode(trigger.name, []);
    } catch (caught) {
      error = caught;
    }
    return {
      calls,
      error,
      loopsDone: [...loops.values()].every((state) => state.done),
      drawsLeft: this.forced.left,
    };
  }
}
