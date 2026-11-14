// Checks the waiter bot without the API. Runs the workflow's own Code nodes from
// workflows/waiter-bot.json with a seeded random: the shares of skipped runs, approvals and far
// deferrals against patterns.md, then whole runs that follow the workflow's connections against a
// stub staff API, one for each row of the story's I/O matrix.
// A failure names its seed; WAITER_SEED=<seed> npm test repeats it. Every draw happens at the top
// of the file, in a `before` hook or in a test, in file order, so a seed repeats every number.
import { before, describe, test } from 'node:test';

import { Checks } from './support/checks.mjs';
import { DAY_MS, DEV_API, MINUTE_MS } from './support/constants.mjs';
import { WorkflowEmulator } from './support/emulator.mjs';
import { ForcedDraws, SeededRandom } from './support/random.mjs';
import { shares } from './support/shares.mjs';
import { StaffApi, WAITER_EMAIL, conflict } from './support/staff-api.mjs';
import { Workflow } from './support/workflow.mjs';

// The waiter's numbers from patterns.md and story 7. Tuning CONFIG away from them fails this check
// until patterns.md and this table follow.
const EXPECTED = {
  skipShare: 0.4,
  approveShare: 0.8,
  farThresholdDays: 3,
  farDeferralShare: 0.5,
  pageSize: 50,
};
const RUNS = 10_000;
const DRAWS = 4_000;
const NOW = Date.parse('2026-11-20T12:00:00+04:00');

const random = new SeededRandom('WAITER_SEED');
console.log(`Seed ${random.seed}`);
const check = new Checks(random);
// A matrix row queues the draws it needs, in the order the Code nodes take them.
const forced = new ForcedDraws(random.next);
const workflow = new Workflow('waiter-bot.json', { random: forced.next, now: NOW });
const emulator = new WorkflowEmulator(workflow, forced);
const execute = (run) => emulator.execute(run);

const startsIn = (ms) => new Date(NOW + ms).toISOString();
const NEAR = startsIn(DAY_MS);
const FAR = startsIn(5 * DAY_MS);
const LOGIN = 'POST /auth/login';
const LIST = `GET /staff/booking-requests?limit=${EXPECTED.pageSize}`;
const approve = (id) => `POST /staff/booking-requests/${id}/approve`;
const reject = (id) => `POST /staff/booking-requests/${id}/reject`;
// Draws: one for the skip in Plan the round, then per request one for a near start or one or two
// for a far start (deferral, then approval).
const NOT_SKIPPED = 0.9;
const APPROVE = 0.5;
const REJECT = 0.9;
const LEAVE = 0.3;
const DECIDE_FAR = 0.7;
const sameCalls = (actual, expected) => actual.join('\n') === expected.join('\n');
const quietRun = (run) => run.error === null && run.loopsDone && run.drawsLeft === 0;

forced.push(NOT_SKIPPED);
const planned = workflow.codeNode('Plan the round').run({})[0];
const { config } = planned;

describe('Workflow', () => {
  const { json } = workflow;
  const trigger = json.nodes.find((entry) => entry.type === 'n8n-nodes-base.scheduleTrigger');
  test('id WaiterBotDecides, name Waiter bot', () => {
    check.ok(
      'id WaiterBotDecides, name Waiter bot',
      json.id === 'WaiterBotDecides' && json.name === 'Waiter bot',
    );
  });
  test('timezone Asia/Tbilisi', () => {
    check.ok('timezone Asia/Tbilisi', json.settings?.timezone === 'Asia/Tbilisi');
  });
  test('scheduled every 5 minutes', () => {
    const interval = trigger?.parameters.rule.interval[0];
    check.ok(
      'scheduled every 5 minutes',
      interval?.field === 'minutes' && interval?.minutesInterval === 5,
    );
  });
  test('no state kept between runs (no workflow static data)', () => {
    const codeSources = json.nodes
      .filter((entry) => entry.type === 'n8n-nodes-base.code')
      .map((entry) => entry.parameters.jsCode);
    check.ok(
      'no state kept between runs (no workflow static data)',
      codeSources.every((source) => !source.includes('getWorkflowStaticData')),
    );
  });
  test('requests are decided one at a time (Loop Over Items v3, batch size 1)', () => {
    const loopNode = json.nodes.find((entry) => entry.type === 'n8n-nodes-base.splitInBatches');
    check.ok(
      'requests are decided one at a time (Loop Over Items v3, batch size 1)',
      loopNode?.typeVersion === 3 && loopNode.parameters.batchSize === 1,
    );
  });
});

describe('Configuration', () => {
  test('apiBaseUrl is the dev API', () => {
    check.ok(`apiBaseUrl is the dev API (${config.apiBaseUrl})`, config.apiBaseUrl === DEV_API);
  });
  test(`signs in as ${WAITER_EMAIL}`, () => {
    check.ok(`signs in as ${WAITER_EMAIL}`, planned.email === WAITER_EMAIL);
  });
  test(`page size ${EXPECTED.pageSize}`, () => {
    check.ok(`page size ${EXPECTED.pageSize}`, config.pageSize === EXPECTED.pageSize);
  });
});

const decide = (startsAt) =>
  workflow.codeNode('Decide the request').run({
    input: [{ ...planned, cookie: 'session', requestId: 'r1', startsAt }],
  })[0].decision;
const decisions = (startsAt) => Array.from({ length: DRAWS }, () => decide(startsAt));
const share = (list, value) => shares(list)(value);

describe(`Shares over ${RUNS} runs and ${DRAWS} decisions`, () => {
  let plans;
  let near;
  let far;
  before(() => {
    plans = Array.from({ length: RUNS }, () => workflow.codeNode('Plan the round').run({}));
    near = decisions(NEAR);
    far = decisions(FAR);
  });
  test('skipped runs', () => {
    check.share(
      'skipped runs',
      plans.filter((output) => output.length === 0).length / RUNS,
      EXPECTED.skipShare,
      RUNS,
    );
  });
  test('near request approved', () => {
    check.share('near request approved', share(near, 'approve'), EXPECTED.approveShare, DRAWS);
  });
  test('near request left', () => {
    check.share('near request left', share(near, 'leave'), 0, DRAWS);
  });
  test('near decisions are approve or reject', () => {
    check.ok(
      'near decisions are approve or reject',
      near.every((value) => ['approve', 'reject'].includes(value)),
    );
  });
  test('far request left', () => {
    check.share('far request left', share(far, 'leave'), EXPECTED.farDeferralShare, DRAWS);
  });
  test('far request approved when decided', () => {
    const farDecided = far.filter((value) => value !== 'leave');
    check.share(
      'far request approved when decided',
      share(farDecided, 'approve'),
      EXPECTED.approveShare,
      farDecided.length,
    );
  });
});

describe('Far threshold', () => {
  const threshold = EXPECTED.farThresholdDays * DAY_MS;
  const days = EXPECTED.farThresholdDays;
  test(`start ${days} days minus a minute ahead never left`, () => {
    check.share(
      `start ${days} days minus a minute ahead never left`,
      share(decisions(startsIn(threshold - MINUTE_MS)), 'leave'),
      0,
      DRAWS,
    );
  });
  test(`start exactly ${days} days ahead never left`, () => {
    check.share(
      `start exactly ${days} days ahead never left`,
      share(decisions(startsIn(threshold)), 'leave'),
      0,
      DRAWS,
    );
  });
  test(`start ${days} days plus a minute ahead left`, () => {
    check.share(
      `start ${days} days plus a minute ahead left`,
      share(decisions(startsIn(threshold + MINUTE_MS)), 'leave'),
      EXPECTED.farDeferralShare,
      DRAWS,
    );
  });
});

describe('I/O matrix: whole runs against a stub staff API', () => {
  test('skipped run: no sign-in, no calls', () => {
    const skipped = execute({ api: new StaffApi().handle, randoms: [0.1] });
    check.ok(
      'skipped run: no sign-in, no calls',
      skipped.error === null && skipped.calls.length === 0,
    );
  });

  describe('no requests', () => {
    let empty;
    before(() => {
      empty = execute({ api: new StaffApi().handle, randoms: [NOT_SKIPPED] });
    });
    test('no requests: the run ends after the list', () => {
      check.ok('no requests: the run ends after the list', quietRun(empty));
    });
    test('no requests: sign-in and one page only', () => {
      check.ok('no requests: sign-in and one page only', sameCalls(empty.calls, [LOGIN, LIST]));
    });
  });

  for (const [label, draw, call] of [
    ['approved', APPROVE, approve],
    ['rejected', REJECT, reject],
  ]) {
    test(`near request ${label}`, () => {
      const run = execute({
        api: new StaffApi({ requests: [{ id: 'near', starts_at: NEAR }] }).handle,
        randoms: [NOT_SKIPPED, draw],
      });
      check.ok(
        `near request ${label}`,
        quietRun(run) && sameCalls(run.calls, [LOGIN, LIST, call('near')]),
      );
    });
  }

  test('far request left for a later run', () => {
    const farLeft = execute({
      api: new StaffApi({ requests: [{ id: 'far', starts_at: FAR }] }).handle,
      randoms: [NOT_SKIPPED, LEAVE],
    });
    check.ok(
      'far request left for a later run',
      quietRun(farLeft) && sameCalls(farLeft.calls, [LOGIN, LIST]),
    );
  });
  for (const [label, draw, call] of [
    ['approved', APPROVE, approve],
    ['rejected', REJECT, reject],
  ]) {
    test(`far request not left is ${label}`, () => {
      const run = execute({
        api: new StaffApi({ requests: [{ id: 'far', starts_at: FAR }] }).handle,
        randoms: [NOT_SKIPPED, DECIDE_FAR, draw],
      });
      check.ok(
        `far request not left is ${label}`,
        quietRun(run) && sameCalls(run.calls, [LOGIN, LIST, call('far')]),
      );
    });
  }

  const competing = () =>
    new StaffApi({
      requests: [
        { id: 'earlier', starts_at: NEAR },
        { id: 'later', starts_at: NEAR },
      ],
    });
  const bothApprovedLabel =
    'competing: the earlier is approved first, the later answers REQUEST_NOT_PENDING and is ' +
    'skipped';
  test(bothApprovedLabel, () => {
    const bothApproved = competing();
    const competingRun = execute({
      api: bothApproved.handle,
      randoms: [NOT_SKIPPED, APPROVE, APPROVE],
    });
    check.ok(
      bothApprovedLabel,
      quietRun(competingRun) &&
        sameCalls(competingRun.calls, [LOGIN, LIST, approve('earlier'), approve('later')]) &&
        bothApproved.status('earlier') === 'CONFIRMED' &&
        bothApproved.status('later') === 'REJECTED',
    );
  });
  test('competing: rejecting the already rejected later one is skipped too', () => {
    const laterRejected = execute({
      api: competing().handle,
      randoms: [NOT_SKIPPED, APPROVE, REJECT],
    });
    check.ok(
      'competing: rejecting the already rejected later one is skipped too',
      quietRun(laterRejected) &&
        sameCalls(laterRejected.calls, [LOGIN, LIST, approve('earlier'), reject('later')]),
    );
  });

  const twoRequests = (answers) =>
    new StaffApi({
      requests: [
        { id: 'first', starts_at: NEAR },
        { id: 'second', starts_at: NEAR, table: 'table-2' },
      ],
      answers,
    });
  const takenLabel =
    'table taken: approve answers SLOT_UNAVAILABLE, the request is rejected, the run goes on';
  test(takenLabel, () => {
    const takenApi = twoRequests({ 'approve first': conflict('SLOT_UNAVAILABLE') });
    const taken = execute({ api: takenApi.handle, randoms: [NOT_SKIPPED, APPROVE, APPROVE] });
    check.ok(
      takenLabel,
      quietRun(taken) &&
        sameCalls(taken.calls, [
          LOGIN,
          LIST,
          approve('first'),
          reject('first'),
          approve('second'),
        ]) &&
        takenApi.status('first') === 'REJECTED',
    );
  });
  test('table taken: a reject answering REQUEST_NOT_PENDING is skipped quietly', () => {
    const takenThenDecided = execute({
      api: twoRequests({
        'approve first': conflict('SLOT_UNAVAILABLE'),
        'reject first': conflict('REQUEST_NOT_PENDING'),
      }).handle,
      randoms: [NOT_SKIPPED, APPROVE, APPROVE],
    });
    check.ok(
      'table taken: a reject answering REQUEST_NOT_PENDING is skipped quietly',
      quietRun(takenThenDecided) &&
        sameCalls(takenThenDecided.calls, [
          LOGIN,
          LIST,
          approve('first'),
          reject('first'),
          approve('second'),
        ]),
    );
  });
  const expiredLabel =
    'expired: approve answers REQUEST_EXPIRED, skipped without a reject, the run goes on';
  test(expiredLabel, () => {
    const expired = execute({
      api: twoRequests({ 'approve first': conflict('REQUEST_EXPIRED') }).handle,
      randoms: [NOT_SKIPPED, APPROVE, APPROVE],
    });
    check.ok(
      expiredLabel,
      quietRun(expired) &&
        sameCalls(expired.calls, [LOGIN, LIST, approve('first'), approve('second')]),
    );
  });

  const failing = [
    ['an approve answering 500', { 'approve first': { statusCode: 500, body: {} } }],
    ['a reject answering 500', { 'reject first': { statusCode: 500, body: {} } }, REJECT],
    ['a failed sign-in (401)', { login: { statusCode: 401, body: {} } }],
    [
      'a list answering 403 STAFF_ONLY',
      { list: { statusCode: 403, body: { code: 'STAFF_ONLY' } } },
    ],
    ['a list answering 500', { list: { statusCode: 500, body: {} } }],
    ['an approve answering 401', { 'approve first': { statusCode: 401, body: {} } }],
    ['an approve answering 404', { 'approve first': { statusCode: 404, body: {} } }],
    ['an approve answering another 409', { 'approve first': conflict('OVERLAPPING_BOOKING') }],
    [
      'a reject after SLOT_UNAVAILABLE answering 500',
      {
        'approve first': conflict('SLOT_UNAVAILABLE'),
        'reject first': { statusCode: 500, body: {} },
      },
    ],
    [
      'a reject answering SLOT_UNAVAILABLE',
      { 'reject first': conflict('SLOT_UNAVAILABLE') },
      REJECT,
    ],
  ];
  for (const [label, answers, draw = APPROVE] of failing) {
    test(`broken API: ${label} fails the run`, () => {
      const run = execute({
        api: twoRequests(answers).handle,
        randoms: [NOT_SKIPPED, draw, APPROVE],
      });
      check.ok(`broken API: ${label} fails the run`, run.error !== null);
    });
  }
});

describe('One page per run', () => {
  const crowd = Array.from({ length: EXPECTED.pageSize + 10 }, (_, index) => ({
    id: `r${index + 1}`,
    starts_at: startsIn(DAY_MS + index * 30 * MINUTE_MS),
    table: `table-${index + 1}`,
  }));
  const label =
    `${crowd.length} pending: one page of ${EXPECTED.pageSize} decided in the API's order`;
  test(label, () => {
    const page = execute({
      api: new StaffApi({ requests: crowd }).handle,
      randoms: [NOT_SKIPPED, ...Array(EXPECTED.pageSize).fill(APPROVE)],
    });
    check.ok(
      label,
      quietRun(page) &&
        sameCalls(page.calls, [
          LOGIN,
          LIST,
          ...crowd.slice(0, EXPECTED.pageSize).map(({ id }) => approve(id)),
        ]),
    );
  });
});
