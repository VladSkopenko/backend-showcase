// Checks the booking simulator without the API. Runs the workflow's own Code nodes from
// workflows/booking-simulator.json on simulated clocks with stub inputs, compares the shares over
// many plans with patterns.md and CONFIG, and checks the decisions of the other Code nodes.
// Usage, from the repository root: node n8n/check-simulator-plan.mjs
// A failure prints its seed; SIMULATOR_SEED=<seed> node n8n/check-simulator-plan.mjs repeats it.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

// The numbers of patterns.md, as shares of 1. Tuning CONFIG away from them fails this check until
// patterns.md and this table follow.
const PATTERNS = {
  regularShare: 0.5,
  favouriteLocationShare: 0.8,
  cancelShare: 0.15,
  leadTime: [
    { group: 'same day', firstDay: 0, lastDay: 0, share: 0.35 },
    { group: 'next day', firstDay: 1, lastDay: 1, share: 0.25 },
    { group: '2 to 3 days', firstDay: 2, lastDay: 3, share: 0.2 },
    { group: '4 to 14 days', firstDay: 4, lastDay: 14, share: 0.2 },
  ],
  dayWeights: { Mon: 1, Tue: 1, Wed: 1, Thu: 1, Fri: 1.5, Sat: 1.5, Sun: 1.2 },
  partySizes: {
    weekday: { 1: 0.15, 2: 0.48, 3: 0.2, 4: 0.15, '5 to 8': 0.02 },
    weekend: { 1: 0.05, 2: 0.35, 3: 0.22, 4: 0.28, '5 to 8': 0.1 },
    '02-14': { 1: 0, 2: 0.9, 3: 0.04, 4: 0.04, '5 to 8': 0.02 },
    '03-08': { 1: 0.05, 2: 0.3, 3: 0.25, 4: 0.25, '5 to 8': 0.15 },
    '12-31': { 1: 0, 2: 0.1, 3: 0.1, 4: 0.3, '5 to 8': 0.5 },
  },
  lunchPeak: ['12:30', '13:00', '13:30', '14:00', '14:30'],
  dinnerPeak: ['18:30', '19:00', '19:30', '20:00', '20:30', '21:00'],
  lowHours: [
    ...['10:00', '10:30', '11:00', '11:30'],
    ...['15:00', '15:30', '16:00', '16:30', '17:00', '17:30'],
  ],
  perPerson: {
    other: { MAIN_COURSE: 0.9, APPETIZER: 0.5, DESSERT: 0.4 },
    lunch: { MAIN_COURSE: 0.9, APPETIZER: 0.5, DESSERT: 0.25 },
    dinner: { MAIN_COURSE: 0.9, APPETIZER: 0.6, DESSERT: 0.4 },
  },
  locationTopDishes: 3,
  locationDishWeight: 3,
  favouriteDishes: 2,
  favouriteDishWeight: 3,
};
const DEV_API = 'https://backend-showcase-dev.duckdns.org/api/v1';
const PLANS = 10_000;
const DRAWS = 4_000;
// A share passes within 4 standard errors of its expected value; an expected 0 must be exactly 0.
const STANDARD_ERRORS = 4;
const MINUTE_MS = 60 * 1000;
const DAY_MS = 24 * 60 * MINUTE_MS;
const REQUEST_LEAD_MS = 120 * MINUTE_MS;
const TBILISI_OFFSET = '+04:00';
// The API's booking grid: starts every 30 minutes from 10:00 to 21:30, Tbilisi time (UTC+4).
const GRID = Array.from({ length: 24 }, (_, index) => {
  const minutes = 10 * 60 + index * 30;
  const pad = (value) => String(value).padStart(2, '0');
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
});

const seed = Number(process.env.SIMULATOR_SEED ?? Math.floor(Math.random() * 2 ** 32));
console.log(`Seed ${seed}`);
// mulberry32: one seeded stream for the script and every Code node, so a seed repeats a run.
let rngState = seed >>> 0;
const random = () => {
  rngState = (rngState + 0x6d2b79f5) >>> 0;
  let value = rngState;
  value = Math.imul(value ^ (value >>> 15), value | 1);
  value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
  return ((value ^ (value >>> 14)) >>> 0) / 2 ** 32;
};

const workflow = JSON.parse(
  readFileSync(new URL('./workflows/booking-simulator.json', import.meta.url), 'utf8'),
);

class CodeNode {
  constructor(name) {
    const node = workflow.nodes.find((entry) => entry.name === name);
    if (!node) {
      throw new Error(`No node named ${name} in the workflow`);
    }
    // n8n runs a Code node's source as a function body, so a top-level return is allowed.
    this.script = new vm.Script(`(() => {\n${node.parameters.jsCode}\n})()`, { filename: name });
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

  run({ now = 0, input = [], nodes = {} }) {
    const items = (list) => ({ first: () => list[0], all: () => list });
    this.clock.now = now;
    this.context.$input = items(input.map((json) => ({ json })));
    this.context.$ = (name) => items(nodes[name].map((json) => ({ json })));
    return [...this.script.runInContext(this.context)].map((item) => item.json);
  }

  throws(run) {
    try {
      this.run(run);
      return false;
    } catch {
      return true;
    }
  }
}

const node = (name) => new CodeNode(name);
const planNode = node('Plan the visit');
const bookGate = node('Book this time?');
const slotPicker = node('Pick a free slot');

const tbilisiDate = (ms) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Tbilisi' }).format(new Date(ms));
const addDays = (date, days) =>
  new Date(Date.parse(`${date}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
const dayName = (date) =>
  ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][new Date(`${date}T00:00:00Z`).getUTCDay()];
const daysAhead = (from, to) => Math.round((Date.parse(to) - Date.parse(from)) / DAY_MS);
const leadGroup = (days) =>
  PATTERNS.leadTime.find(({ firstDay, lastDay }) => firstDay <= days && days <= lastDay)?.group ??
  `${days} days`;
const sizeGroup = (partySize) => (partySize > 4 ? '5 to 8' : String(partySize));
const startInstant = (date, time) => Date.parse(`${date}T${time}:00${TBILISI_OFFSET}`);
// FNV-1a ranking, written here on its own to check the workflow's favourites.
const stableHash = (text) => {
  let hash = 0x811c9dc5;
  for (const char of text) {
    hash = Math.imul(hash ^ char.codePointAt(0), 0x01000193) >>> 0;
  }
  return hash;
};
const rankByHash = (seedText, ids) =>
  [...ids].sort((a, b) => stableHash(`${seedText}|${a}`) - stableHash(`${seedText}|${b}`));

const failures = [];
const expect = (label, condition) => {
  if (!condition) {
    failures.push(label);
  }
  console.log(`${condition ? 'ok  ' : 'FAIL'} ${label}`);
};
const report = (label, actual, expected, count) => {
  const tolerance = STANDARD_ERRORS * Math.sqrt((expected * (1 - expected)) / count);
  const ok = Math.abs(actual - expected) <= tolerance;
  if (!ok) {
    failures.push(label);
  }
  console.log(
    `${ok ? 'ok  ' : 'FAIL'} ${label}: ${actual.toFixed(3)} ` +
      `(expected ${expected.toFixed(3)} +- ${tolerance.toFixed(3)}, n ${count})`,
  );
};
const shares = (values) => {
  const counts = {};
  for (const value of values) {
    counts[value] = (counts[value] ?? 0) + 1;
  }
  return (key) => (counts[key] ?? 0) / values.length;
};
const normalized = (weights) => {
  const total = Object.values(weights).reduce((sum, weight) => sum + weight, 0);
  return Object.fromEntries(Object.entries(weights).map(([key, weight]) => [key, weight / total]));
};

// A search answer where every start after now is free on the given number of fitting tables.
const openGrid = (date, now, tableCount) => ({
  items: Array.from({ length: tableCount }, (_, index) => ({
    id: `table-${index + 1}`,
    slots: GRID.map((time) => ({
      starts_at: `${date}T${time}:00${TBILISI_OFFSET}`,
      available: startInstant(date, time) > now,
    })),
  })),
});
const plan = (now) => planNode.run({ now })[0];
// Runs Book this time? and Pick a free slot for a plan as a book run; null when nothing is sent.
const pickStart = (visit, now, search) => {
  const gather = [{ ...visit, action: 'book' }];
  const passed = bookGate.run({ now, nodes: { 'Gather the visit': gather } });
  if (passed.length === 0) {
    return null;
  }
  const picked = slotPicker.run({
    now,
    input: [search],
    nodes: { 'Choose the location': [{ ...passed[0], locationId: 'location-1' }] },
  });
  return picked.length === 0 ? null : picked[0];
};

// Ordinary days: clocks spread over four weeks from Monday 16 November 2026, no holiday in reach.
const firstDay = Date.parse(`2026-11-16T00:00:00${TBILISI_OFFSET}`);
const samples = Array.from({ length: PLANS }, () => {
  const now = firstDay + Math.floor(random() * 28 * DAY_MS);
  return { now, today: tbilisiDate(now), visit: plan(now) };
});
const visits = samples.map(({ visit }) => visit);
const { config } = visits[0];

console.log('Configuration');
expect(`apiBaseUrl is the dev API (${config.apiBaseUrl})`, config.apiBaseUrl === DEV_API);

console.log(`Personas and actions over ${PLANS} plans`);
const regular = visits.filter(({ botNumber }) => botNumber >= 1 && botNumber <= 10);
report('regular share (bots 1 to 10)', regular.length / PLANS, PATTERNS.regularShare, PLANS);
expect(
  'regular plans are bots 1 to 10',
  visits.every(({ botNumber, persona }) => (persona.name === 'regular') === botNumber <= 10),
);
expect(
  'every bot from 1 to 40 plays',
  new Set(visits.map(({ botNumber }) => botNumber)).size === 40 &&
    visits.every(({ botNumber }) => botNumber >= 1 && botNumber <= 40),
);
report(
  'cancel share',
  visits.filter(({ action }) => action === 'cancel').length / PLANS,
  PATTERNS.cancelShare,
  PLANS,
);
report(
  'approved pre-order share (CONFIG.approvedPreorderChance)',
  visits.filter(({ preorderApproved }) => preorderApproved).length / PLANS,
  config.approvedPreorderChance,
  PLANS,
);

console.log('Lead time and day of the week');
const leadShare = shares(
  samples.map(({ today, visit }) => leadGroup(daysAhead(today, visit.date))),
);
for (const { group, share } of PATTERNS.leadTime) {
  report(`lead ${group}`, leadShare(group), share, PLANS);
}
// Expected weekday shares: every group's share spread over its days, each day weighted by the
// patterns.md day weights, averaged over the sampled clocks.
const expectedDays = Object.fromEntries(Object.keys(PATTERNS.dayWeights).map((day) => [day, 0]));
for (const { today } of samples) {
  const weights = PATTERNS.leadTime.flatMap(({ firstDay: first, lastDay: last, share }) =>
    Array.from({ length: last - first + 1 }, (_, index) => {
      const day = dayName(addDays(today, first + index));
      return [day, (share / (last - first + 1)) * PATTERNS.dayWeights[day]];
    }),
  );
  const total = weights.reduce((sum, [, weight]) => sum + weight, 0);
  for (const [day, weight] of weights) {
    expectedDays[day] += weight / total / PLANS;
  }
}
const dayShare = shares(visits.map(({ date }) => dayName(date)));
for (const [day, expected] of Object.entries(expectedDays)) {
  report(`booking dates on ${day}`, dayShare(day), expected, PLANS);
}

console.log('Start hours (dates after today, every start open)');
const futureSamples = samples.filter(({ today, visit }) => visit.date > today);
const starts = futureSamples
  .map(({ now, visit }) => pickStart(visit, now, openGrid(visit.date, now, 4)))
  .filter(Boolean)
  .map(({ startsAt }) => startsAt.slice(11, 16));
expect('every future plan picks a start', starts.length === futureSamples.length);
const hourShare = shares(starts);
const startShares = normalized(config.startWeights);
for (const time of GRID) {
  report(
    `start ${time} (CONFIG.startWeights)`,
    hourShare(time),
    startShares[time] ?? 0,
    starts.length,
  );
}
const lowest = (times) => Math.min(...times.map(hourShare));
const highest = (times) => Math.max(...times.map(hourShare));
expect(
  'every lunch-peak start beats every low-hour start',
  lowest(PATTERNS.lunchPeak) > highest(PATTERNS.lowHours),
);
expect(
  'every dinner-peak start beats every low-hour start',
  lowest(PATTERNS.dinnerPeak) > highest(PATTERNS.lowHours),
);

console.log('Party sizes');
const checkPartySizes = (label, plans, expected) => {
  const share = shares(plans.map(({ partySize }) => sizeGroup(partySize)));
  for (const [size, value] of Object.entries(expected)) {
    report(`party ${size} on ${label}`, share(size), value, plans.length);
  }
};
const isWeekend = ({ date }) => config.weekendDays.includes(dayName(date));
checkPartySizes(
  'weekdays',
  visits.filter((visit) => !isWeekend(visit)),
  PATTERNS.partySizes.weekday,
);
checkPartySizes('weekends', visits.filter(isWeekend), PATTERNS.partySizes.weekend);
// Holidays: clocks between midnight and 9:00 on the day, so about a third of plans book that day.
for (const date of ['2027-02-14', '2027-03-08', '2026-12-31']) {
  const midnight = Date.parse(`${date}T00:00:00${TBILISI_OFFSET}`);
  const onHoliday = Array.from({ length: PLANS }, () =>
    plan(midnight + Math.floor(random() * 9 * 60 * MINUTE_MS)),
  ).filter((visit) => visit.date === date);
  checkPartySizes(date, onHoliday, PATTERNS.partySizes[date.slice(5)]);
}
const requestSamples = samples.filter(({ visit }) => visit.partySize > 4);
const requestShare = shares(requestSamples.map(({ visit }) => String(visit.partySize)));
for (const [size, expected] of Object.entries(normalized(config.requestPartySizes))) {
  report(
    `request of ${size} (CONFIG.requestPartySizes)`,
    requestShare(size),
    expected,
    requestSamples.length,
  );
}

console.log('Requests');
let sent = 0;
let tooClose = 0;
let possible = 0;
for (const { now, visit } of requestSamples) {
  possible += GRID.some((time) => startInstant(visit.date, time) > now + REQUEST_LEAD_MS) ? 1 : 0;
  const picked = pickStart(visit, now, openGrid(visit.date, now, 1));
  if (picked) {
    sent += 1;
    tooClose += Date.parse(picked.startsAt) <= now + REQUEST_LEAD_MS ? 1 : 0;
  }
}
console.log(`  ${requestSamples.length} request plans, ${possible} with a start beyond 2 hours`);
expect(`requests are sent on a one-table grid (${sent})`, sent > 0);
expect(
  'a request is sent exactly when a start beyond 2 hours exists',
  sent === possible,
);
expect('no request starts within 2 hours', tooClose === 0);
expect(
  'requests are 5 to 8 people',
  requestSamples.every(({ visit }) => visit.partySize <= 8),
);

console.log('Free tables rule');
const instantSample = samples.find(
  ({ visit, today }) => visit.partySize <= 4 && visit.date > today,
);
const tryTables = (count) =>
  pickStart(
    instantSample.visit,
    instantSample.now,
    openGrid(instantSample.visit.date, instantSample.now, count),
  );
expect('an instant booking skips starts with 3 free tables', tryTables(3) === null);
expect('an instant booking takes a start with 4 free tables', tryTables(4) !== null);

console.log('Locations');
const locationNode = node('Choose the location');
const locations = ['location-a', 'location-b', 'location-c'];
const personaOf = (name) => config.personas.find((persona) => persona.name === name);
const chooseLocations = (botNumber, persona) =>
  Array.from(
    { length: DRAWS },
    () =>
      locationNode.run({
        input: [{ body: locations.map((id) => ({ id })) }],
        nodes: { 'Book this time?': [{ botNumber, persona }] },
      })[0].locationId,
  );
const regularBot = 3;
const favourite = rankByHash(`bot-${regularBot}`, locations)[0];
const regularShare = shares(chooseLocations(regularBot, personaOf('regular')));
report(
  `regular at the favourite location`,
  regularShare(favourite),
  PATTERNS.favouriteLocationShare,
  DRAWS,
);
for (const id of locations.filter((id) => id !== favourite)) {
  report(
    `regular at ${id}`,
    regularShare(id),
    (1 - PATTERNS.favouriteLocationShare) / 2,
    DRAWS,
  );
}
const occasionalShare = shares(chooseLocations(25, personaOf('occasional')));
for (const id of locations) {
  report(`occasional at ${id}`, occasionalShare(id), 1 / 3, DRAWS);
}

console.log('Pre-order');
const composeNode = node('Compose the pre-order');
const categories = ['APPETIZER', 'MAIN_COURSE', 'DESSERT'];
const dishes = categories.flatMap((category) =>
  Array.from({ length: 5 }, (_, index) => ({
    id: `${category.toLowerCase()}-${index}`,
    category,
    is_available: index !== 4,
  })),
);
const unavailable = new Set(dishes.filter((dish) => !dish.is_available).map((dish) => dish.id));
const compose = ({ botNumber, persona, time, partySize = 1, locationId = 'location-a' }) =>
  composeNode.run({
    input: [
      {
        apiBaseUrl: DEV_API,
        cookie: 'session',
        bookingId: 'booking-1',
        partySize,
        startsAt: `2026-12-01T${time}:00${TBILISI_OFFSET}`,
        locationId,
        next: 'end',
      },
    ],
    nodes: { 'Gather the visit': [{ config, botNumber, persona, dishes }] },
  })[0];
const categoryOf = Object.fromEntries(dishes.map((dish) => [dish.id, dish.category]));
let orderedUnavailable = false;
for (const [meal, time] of [['other', '16:00'], ['lunch', '13:00'], ['dinner', '19:30']]) {
  const orders = Array.from({ length: DRAWS }, () =>
    compose({ botNumber: 25, persona: personaOf('occasional'), time }),
  );
  orderedUnavailable ||= orders.some(({ lines }) =>
    lines.some(({ dishId }) => unavailable.has(dishId)),
  );
  for (const [category, chance] of Object.entries(PATTERNS.perPerson[meal])) {
    const ordered = orders.filter(({ lines }) =>
      lines.some(({ dishId }) => categoryOf[dishId] === category),
    ).length;
    report(`${category} per person at ${time} (${meal})`, ordered / DRAWS, chance, DRAWS);
  }
}
expect('no order holds an unavailable dish', !orderedUnavailable);
const occasional = { botNumber: 25, persona: personaOf('occasional') };
const party = compose({ ...occasional, time: '19:30', partySize: 6 });
expect(
  'a party of 6 orders at most one dish per category and person',
  categories.every(
    (category) =>
      party.lines
        .filter(({ dishId }) => categoryOf[dishId] === category)
        .reduce((sum, { quantity }) => sum + quantity, 0) <= 6,
  ),
);
const empty = composeNode.run({
  input: [{ next: 'action' }],
  nodes: { 'Gather the visit': [{ config, ...occasional, dishes }] },
})[0];
expect('no approved request to order for gives an empty order', empty.lines.length === 0);
// Dish weights for the main courses: the location's top dishes and a regular's favourites.
const checkDishWeights = (label, botNumber, persona) => {
  const ids = dishes.map((dish) => dish.id);
  const top = new Set(rankByHash('location-location-a', ids).slice(0, PATTERNS.locationTopDishes));
  const favourites = new Set(rankByHash(`bot-${botNumber}`, ids).slice(0, persona.favouriteDishes));
  const mains = dishes.filter((dish) => dish.category === 'MAIN_COURSE' && dish.is_available);
  const expected = normalized(
    Object.fromEntries(
      mains.map((dish) => [
        dish.id,
        (top.has(dish.id) ? PATTERNS.locationDishWeight : 1) *
          (favourites.has(dish.id) ? PATTERNS.favouriteDishWeight : 1),
      ]),
    ),
  );
  const picks = Array.from({ length: DRAWS }, () => compose({ botNumber, persona, time: '19:30' }))
    .flatMap(({ lines }) => lines.filter(({ dishId }) => categoryOf[dishId] === 'MAIN_COURSE'))
    .map(({ dishId }) => dishId);
  const share = shares(picks);
  for (const [id, value] of Object.entries(expected)) {
    report(`${label}: ${id}`, share(id), value, picks.length);
  }
};
expect(
  'regulars have the patterns.md number of favourite dishes',
  personaOf('regular').favouriteDishes === PATTERNS.favouriteDishes,
);
checkDishWeights('occasional main course', 25, personaOf('occasional'));
checkDishWeights('regular main course', regularBot, personaOf('regular'));

console.log('Answers');
const now = Date.parse(`2026-11-20T12:00:00${TBILISI_OFFSET}`);
const bookingCheck = node('Check the booking answer');
const bookingAnswer = (statusCode, body = {}) => ({
  now,
  input: [{ statusCode, body }],
  nodes: { 'Pick a free slot': [{ config, apiBaseUrl: DEV_API, cookie: 'session' }] },
});
const booked = (status, minutesAhead) => ({
  id: 'booking-1',
  status,
  party_size: 2,
  starts_at: new Date(now + minutesAhead * MINUTE_MS).toISOString(),
  location: { id: 'location-a' },
});
expect('a booking 409 ends quietly', bookingCheck.run(bookingAnswer(409)).length === 0);
expect('a booking 500 fails the run', bookingCheck.throws(bookingAnswer(500)));
expect('a booking 401 fails the run', bookingCheck.throws(bookingAnswer(401)));
expect(
  'a PENDING request gets no pre-order',
  bookingCheck.run(bookingAnswer(201, booked('PENDING', 3 * 24 * 60))).length === 0,
);
expect(
  'a booking starting within 30 minutes gets no pre-order',
  bookingCheck.run(bookingAnswer(201, booked('CONFIRMED', 20))).length === 0,
);
const toPreorder = bookingCheck.run(bookingAnswer(201, booked('CONFIRMED', 120)));
expect(
  'a CONFIRMED booking ahead goes to the pre-order and then ends',
  toPreorder.length === 1 &&
    toPreorder[0].bookingId === 'booking-1' &&
    toPreorder[0].next === 'end',
);
const dishesCheck = node('Check the dishes');
const dishAnswers = (...statuses) => ({
  input: statuses.map((statusCode) => ({ statusCode, body: {} })),
  nodes: { 'Compose the pre-order': [{ bookingId: 'booking-1', next: 'action' }] },
});
expect(
  'a dish 409 is skipped and the rest is submitted',
  dishesCheck.run(dishAnswers(200, 409, 200))[0].added === 2,
);
expect('only 409s leave nothing to submit', dishesCheck.run(dishAnswers(409))[0].added === 0);
expect('a dish 500 fails the run', dishesCheck.throws(dishAnswers(200, 500)));
const submitCheck = node('Check the submit answer');
const submitAnswer = (statusCode) => ({
  input: [{ statusCode, body: {} }],
  nodes: { 'Check the dishes': [{ next: 'action' }] },
});
expect(
  'a submit 200 and 409 go on to the next step',
  submitCheck.run(submitAnswer(200))[0].next === 'action' &&
    submitCheck.run(submitAnswer(409))[0].next === 'action',
);
expect('a submit 500 fails the run', submitCheck.throws(submitAnswer(500)));
const gatherNode = node('Gather the visit');
expect(
  'a menu longer than one page fails the run',
  gatherNode.throws({
    input: [{ items: dishes, total: dishes.length + 1 }],
    nodes: { 'Keep the session': [{}], 'List my bookings': [{ body: [] }] },
  }),
);

console.log('Approved requests');
const findApproved = node('Find approved requests');
const request = (id, overrides) => ({
  id,
  role: 'OWNER',
  status: 'CONFIRMED',
  party_size: 6,
  starts_at: new Date(now + 2 * 24 * 60 * MINUTE_MS).toISOString(),
  location: { id: 'location-a' },
  ...overrides,
});
const bookings = [
  request('open'),
  request('soon-enough', { starts_at: new Date(now + 45 * MINUTE_MS).toISOString() }),
  request('guest', { role: 'GUEST' }),
  request('pending', { status: 'PENDING' }),
  request('small', { party_size: 4 }),
  request('too-close', { starts_at: new Date(now + 20 * MINUTE_MS).toISOString() }),
];
const visitWith = (preorderApproved) => ({
  config,
  apiBaseUrl: DEV_API,
  cookie: 'session',
  preorderApproved,
  bookings,
});
const found = findApproved.run({ now, input: [visitWith(true)] })[0].candidates;
expect(
  'approved requests are own, confirmed, above 4 people and more than 30 minutes ahead',
  found.map(({ bookingId }) => bookingId).join() === 'open,soon-enough',
);
expect(
  'without the approved pre-order chance no request is looked at',
  findApproved.run({ now, input: [visitWith(false)] })[0].candidates.length === 0,
);
const noteParts = node('Note the parts');
const noted = noteParts.run({
  input: [{ parts: [] }, { parts: [{ id: 'part-1' }] }],
  nodes: { 'Check approved requests': found },
});
const pickApproved = node('Pick an approved request');
const picked = pickApproved.run({
  input: [{ items: [] }, { items: [] }],
  nodes: { 'Note the parts': noted },
});
expect(
  'a request with a submitted part is skipped',
  picked.length === 1 && picked[0].bookingId === 'open' && picked[0].next === 'action',
);
const withDraft = pickApproved.run({
  input: [{ items: [{ id: 'line-1' }] }, { items: [] }],
  nodes: { 'Note the parts': noted },
});
expect(
  'a request with a draft left in its cart is skipped, and the run goes on to the action',
  withDraft.length === 1 && withDraft[0].bookingId === undefined && withDraft[0].next === 'action',
);

if (failures.length > 0) {
  console.log(`\n${failures.length} check(s) failed; repeat with SIMULATOR_SEED=${seed}`);
  process.exit(1);
}
console.log(
  '\nAll checks passed: shares within tolerance of patterns.md and CONFIG, decisions as expected',
);
