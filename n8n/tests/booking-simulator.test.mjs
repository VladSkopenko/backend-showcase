// Checks the booking simulator without the API. Runs the workflow's own Code nodes from
// workflows/booking-simulator.json on simulated clocks with stub inputs, compares the shares over
// many plans with patterns.md and CONFIG, and checks the decisions of the other Code nodes.
// A failure names its seed; SIMULATOR_SEED=<seed> npm test repeats it. Every draw happens at the
// top of the file, in a `before` hook or in a test, in file order, so a seed repeats every number.
import { before, describe, test } from 'node:test';

import { Checks } from './support/checks.mjs';
import { DAY_MS, DEV_API, MINUTE_MS } from './support/constants.mjs';
import { SeededRandom } from './support/random.mjs';
import { normalized, shares } from './support/shares.mjs';
import { Workflow } from './support/workflow.mjs';

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
const PLANS = 10_000;
const DRAWS = 4_000;
const REQUEST_LEAD_MS = 120 * MINUTE_MS;
const TBILISI_OFFSET = '+04:00';
// The API's booking grid: starts every 30 minutes from 10:00 to 21:30, Tbilisi time (UTC+4).
const GRID = Array.from({ length: 24 }, (_, index) => {
  const minutes = 10 * 60 + index * 30;
  const pad = (value) => String(value).padStart(2, '0');
  return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`;
});

const random = new SeededRandom('SIMULATOR_SEED');
console.log(`Seed ${random.seed}`);
const check = new Checks(random);
const workflow = new Workflow('booking-simulator.json', { random: random.next });
const node = (name) => workflow.codeNode(name);
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
  const now = firstDay + Math.floor(random.next() * 28 * DAY_MS);
  return { now, today: tbilisiDate(now), visit: plan(now) };
});
const visits = samples.map(({ visit }) => visit);
const { config } = visits[0];
const personaOf = (name) => config.personas.find((persona) => persona.name === name);
const regularBot = 3;
const categories = ['APPETIZER', 'MAIN_COURSE', 'DESSERT'];
const dishes = categories.flatMap((category) =>
  Array.from({ length: 5 }, (_, index) => ({
    id: `${category.toLowerCase()}-${index}`,
    category,
    is_available: index !== 4,
  })),
);

describe('Configuration', () => {
  test('apiBaseUrl is the dev API', () => {
    check.ok(`apiBaseUrl is the dev API (${config.apiBaseUrl})`, config.apiBaseUrl === DEV_API);
  });
});

describe(`Personas and actions over ${PLANS} plans`, () => {
  test('regular share (bots 1 to 10)', () => {
    const regular = visits.filter(({ botNumber }) => botNumber >= 1 && botNumber <= 10);
    check.share(
      'regular share (bots 1 to 10)',
      regular.length / PLANS,
      PATTERNS.regularShare,
      PLANS,
    );
  });
  test('regular plans are bots 1 to 10', () => {
    check.ok(
      'regular plans are bots 1 to 10',
      visits.every(({ botNumber, persona }) => (persona.name === 'regular') === botNumber <= 10),
    );
  });
  test('every bot from 1 to 40 plays', () => {
    check.ok(
      'every bot from 1 to 40 plays',
      new Set(visits.map(({ botNumber }) => botNumber)).size === 40 &&
        visits.every(({ botNumber }) => botNumber >= 1 && botNumber <= 40),
    );
  });
  test('cancel share', () => {
    check.share(
      'cancel share',
      visits.filter(({ action }) => action === 'cancel').length / PLANS,
      PATTERNS.cancelShare,
      PLANS,
    );
  });
  test('approved pre-order share (CONFIG.approvedPreorderChance)', () => {
    check.share(
      'approved pre-order share (CONFIG.approvedPreorderChance)',
      visits.filter(({ preorderApproved }) => preorderApproved).length / PLANS,
      config.approvedPreorderChance,
      PLANS,
    );
  });
});

describe('Lead time and day of the week', () => {
  const leadShare = shares(
    samples.map(({ today, visit }) => leadGroup(daysAhead(today, visit.date))),
  );
  for (const { group, share } of PATTERNS.leadTime) {
    test(`lead ${group}`, () => {
      check.share(`lead ${group}`, leadShare(group), share, PLANS);
    });
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
    test(`booking dates on ${day}`, () => {
      check.share(`booking dates on ${day}`, dayShare(day), expected, PLANS);
    });
  }
});

describe('Start hours (dates after today, every start open)', () => {
  const futureSamples = samples.filter(({ today, visit }) => visit.date > today);
  let starts;
  let hourShare;
  before(() => {
    starts = futureSamples
      .map(({ now, visit }) => pickStart(visit, now, openGrid(visit.date, now, 4)))
      .filter(Boolean)
      .map(({ startsAt }) => startsAt.slice(11, 16));
    hourShare = shares(starts);
  });
  test('every future plan picks a start', () => {
    check.ok('every future plan picks a start', starts.length === futureSamples.length);
  });
  const startShares = normalized(config.startWeights);
  for (const time of GRID) {
    test(`start ${time} (CONFIG.startWeights)`, () => {
      check.share(
        `start ${time} (CONFIG.startWeights)`,
        hourShare(time),
        startShares[time] ?? 0,
        starts.length,
      );
    });
  }
  const lowest = (times) => Math.min(...times.map(hourShare));
  const highest = (times) => Math.max(...times.map(hourShare));
  test('every lunch-peak start beats every low-hour start', () => {
    check.ok(
      'every lunch-peak start beats every low-hour start',
      lowest(PATTERNS.lunchPeak) > highest(PATTERNS.lowHours),
    );
  });
  test('every dinner-peak start beats every low-hour start', () => {
    check.ok(
      'every dinner-peak start beats every low-hour start',
      lowest(PATTERNS.dinnerPeak) > highest(PATTERNS.lowHours),
    );
  });
});

describe('Party sizes', () => {
  const partySizeTests = (label, plansOf, expected) => {
    for (const [size, value] of Object.entries(expected)) {
      test(`party ${size} on ${label}`, () => {
        const plans = plansOf();
        const share = shares(plans.map(({ partySize }) => sizeGroup(partySize)));
        check.share(`party ${size} on ${label}`, share(size), value, plans.length);
      });
    }
  };
  const isWeekend = ({ date }) => config.weekendDays.includes(dayName(date));
  partySizeTests(
    'weekdays',
    () => visits.filter((visit) => !isWeekend(visit)),
    PATTERNS.partySizes.weekday,
  );
  partySizeTests('weekends', () => visits.filter(isWeekend), PATTERNS.partySizes.weekend);
  // Holidays: clocks between midnight and 9:00 on the day, so about a third of plans book that day.
  const holidays = ['2027-02-14', '2027-03-08', '2026-12-31'];
  const onHoliday = {};
  before(() => {
    for (const date of holidays) {
      const midnight = Date.parse(`${date}T00:00:00${TBILISI_OFFSET}`);
      onHoliday[date] = Array.from({ length: PLANS }, () =>
        plan(midnight + Math.floor(random.next() * 9 * 60 * MINUTE_MS)),
      ).filter((visit) => visit.date === date);
    }
  });
  for (const date of holidays) {
    partySizeTests(date, () => onHoliday[date], PATTERNS.partySizes[date.slice(5)]);
  }
  const requestSamples = samples.filter(({ visit }) => visit.partySize > 4);
  const requestShare = shares(requestSamples.map(({ visit }) => String(visit.partySize)));
  for (const [size, expected] of Object.entries(normalized(config.requestPartySizes))) {
    test(`request of ${size} (CONFIG.requestPartySizes)`, () => {
      check.share(
        `request of ${size} (CONFIG.requestPartySizes)`,
        requestShare(size),
        expected,
        requestSamples.length,
      );
    });
  }
});

describe('Requests', () => {
  const requestSamples = samples.filter(({ visit }) => visit.partySize > 4);
  let sent = 0;
  let tooClose = 0;
  let possible = 0;
  before(() => {
    for (const { now, visit } of requestSamples) {
      possible += GRID.some((time) => startInstant(visit.date, time) > now + REQUEST_LEAD_MS)
        ? 1
        : 0;
      const picked = pickStart(visit, now, openGrid(visit.date, now, 1));
      if (picked) {
        sent += 1;
        tooClose += Date.parse(picked.startsAt) <= now + REQUEST_LEAD_MS ? 1 : 0;
      }
    }
  });
  test('requests are sent on a one-table grid', () => {
    check.ok(`requests are sent on a one-table grid (${sent})`, sent > 0);
  });
  test('a request is sent exactly when a start beyond 2 hours exists', () => {
    check.ok(
      `a request is sent exactly when a start beyond 2 hours exists (${requestSamples.length} ` +
        `request plans, ${possible} with a start beyond 2 hours, ${sent} sent)`,
      sent === possible,
    );
  });
  test('no request starts within 2 hours', () => {
    check.ok('no request starts within 2 hours', tooClose === 0);
  });
  test('requests are 5 to 8 people', () => {
    check.ok(
      'requests are 5 to 8 people',
      requestSamples.every(({ visit }) => visit.partySize <= 8),
    );
  });
});

describe('Free tables rule', () => {
  const instantSample = samples.find(
    ({ visit, today }) => visit.partySize <= 4 && visit.date > today,
  );
  const tryTables = (count) =>
    pickStart(
      instantSample.visit,
      instantSample.now,
      openGrid(instantSample.visit.date, instantSample.now, count),
    );
  test('an instant booking skips starts with 3 free tables', () => {
    check.ok('an instant booking skips starts with 3 free tables', tryTables(3) === null);
  });
  test('an instant booking takes a start with 4 free tables', () => {
    check.ok('an instant booking takes a start with 4 free tables', tryTables(4) !== null);
  });
});

describe('Locations', () => {
  const locationNode = node('Choose the location');
  const locations = ['location-a', 'location-b', 'location-c'];
  const chooseLocations = (botNumber, persona) =>
    Array.from(
      { length: DRAWS },
      () =>
        locationNode.run({
          input: [{ body: locations.map((id) => ({ id })) }],
          nodes: { 'Book this time?': [{ botNumber, persona }] },
        })[0].locationId,
    );
  const favourite = rankByHash(`bot-${regularBot}`, locations)[0];
  let regularShare;
  let occasionalShare;
  before(() => {
    regularShare = shares(chooseLocations(regularBot, personaOf('regular')));
    occasionalShare = shares(chooseLocations(25, personaOf('occasional')));
  });
  test('regular at the favourite location', () => {
    check.share(
      'regular at the favourite location',
      regularShare(favourite),
      PATTERNS.favouriteLocationShare,
      DRAWS,
    );
  });
  for (const id of locations.filter((id) => id !== favourite)) {
    test(`regular at ${id}`, () => {
      check.share(
        `regular at ${id}`,
        regularShare(id),
        (1 - PATTERNS.favouriteLocationShare) / 2,
        DRAWS,
      );
    });
  }
  for (const id of locations) {
    test(`occasional at ${id}`, () => {
      check.share(`occasional at ${id}`, occasionalShare(id), 1 / 3, DRAWS);
    });
  }
});

describe('Pre-order', () => {
  const composeNode = node('Compose the pre-order');
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
  const meals = [
    ['other', '16:00'],
    ['lunch', '13:00'],
    ['dinner', '19:30'],
  ];
  const occasional = { botNumber: 25, persona: personaOf('occasional') };
  // Dish weights for the main courses: the location's top dishes and a regular's favourites.
  const expectedDishWeights = (botNumber, persona) => {
    const ids = dishes.map((dish) => dish.id);
    const top = new Set(
      rankByHash('location-location-a', ids).slice(0, PATTERNS.locationTopDishes),
    );
    const favourites = new Set(
      rankByHash(`bot-${botNumber}`, ids).slice(0, persona.favouriteDishes),
    );
    const mains = dishes.filter((dish) => dish.category === 'MAIN_COURSE' && dish.is_available);
    return normalized(
      Object.fromEntries(
        mains.map((dish) => [
          dish.id,
          (top.has(dish.id) ? PATTERNS.locationDishWeight : 1) *
            (favourites.has(dish.id) ? PATTERNS.favouriteDishWeight : 1),
        ]),
      ),
    );
  };
  const mainCoursePicks = (botNumber, persona) =>
    Array.from({ length: DRAWS }, () => compose({ botNumber, persona, time: '19:30' }))
      .flatMap(({ lines }) => lines.filter(({ dishId }) => categoryOf[dishId] === 'MAIN_COURSE'))
      .map(({ dishId }) => dishId);
  const dishWeightGroups = [
    ['occasional main course', 25, personaOf('occasional')],
    ['regular main course', regularBot, personaOf('regular')],
  ];

  const ordersByMeal = {};
  let orderedUnavailable = false;
  let party;
  let empty;
  const picksByGroup = {};
  before(() => {
    for (const [meal, time] of meals) {
      const orders = Array.from({ length: DRAWS }, () => compose({ ...occasional, time }));
      orderedUnavailable ||= orders.some(({ lines }) =>
        lines.some(({ dishId }) => unavailable.has(dishId)),
      );
      ordersByMeal[meal] = orders;
    }
    party = compose({ ...occasional, time: '19:30', partySize: 6 });
    empty = composeNode.run({
      input: [{ next: 'action' }],
      nodes: { 'Gather the visit': [{ config, ...occasional, dishes }] },
    })[0];
    for (const [label, botNumber, persona] of dishWeightGroups) {
      picksByGroup[label] = mainCoursePicks(botNumber, persona);
    }
  });

  for (const [meal, time] of meals) {
    for (const [category, chance] of Object.entries(PATTERNS.perPerson[meal])) {
      test(`${category} per person at ${time} (${meal})`, () => {
        const ordered = ordersByMeal[meal].filter(({ lines }) =>
          lines.some(({ dishId }) => categoryOf[dishId] === category),
        ).length;
        check.share(`${category} per person at ${time} (${meal})`, ordered / DRAWS, chance, DRAWS);
      });
    }
  }
  test('no order holds an unavailable dish', () => {
    check.ok('no order holds an unavailable dish', !orderedUnavailable);
  });
  test('a party of 6 orders at most one dish per category and person', () => {
    check.ok(
      'a party of 6 orders at most one dish per category and person',
      categories.every(
        (category) =>
          party.lines
            .filter(({ dishId }) => categoryOf[dishId] === category)
            .reduce((sum, { quantity }) => sum + quantity, 0) <= 6,
      ),
    );
  });
  test('no approved request to order for gives an empty order', () => {
    check.ok('no approved request to order for gives an empty order', empty.lines.length === 0);
  });
  test('regulars have the patterns.md number of favourite dishes', () => {
    check.ok(
      'regulars have the patterns.md number of favourite dishes',
      personaOf('regular').favouriteDishes === PATTERNS.favouriteDishes,
    );
  });
  for (const [label, botNumber, persona] of dishWeightGroups) {
    for (const [id, value] of Object.entries(expectedDishWeights(botNumber, persona))) {
      test(`${label}: ${id}`, () => {
        const picks = picksByGroup[label];
        check.share(`${label}: ${id}`, shares(picks)(id), value, picks.length);
      });
    }
  }
});

describe('Answers', () => {
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
  test('a booking 409 ends quietly', () => {
    check.ok('a booking 409 ends quietly', bookingCheck.run(bookingAnswer(409)).length === 0);
  });
  test('a booking 500 fails the run', () => {
    check.throws('a booking 500 fails the run', () => bookingCheck.run(bookingAnswer(500)));
  });
  test('a booking 401 fails the run', () => {
    check.throws('a booking 401 fails the run', () => bookingCheck.run(bookingAnswer(401)));
  });
  test('a PENDING request gets no pre-order', () => {
    check.ok(
      'a PENDING request gets no pre-order',
      bookingCheck.run(bookingAnswer(201, booked('PENDING', 3 * 24 * 60))).length === 0,
    );
  });
  test('a booking starting within 30 minutes gets no pre-order', () => {
    check.ok(
      'a booking starting within 30 minutes gets no pre-order',
      bookingCheck.run(bookingAnswer(201, booked('CONFIRMED', 20))).length === 0,
    );
  });
  test('a CONFIRMED booking ahead goes to the pre-order and then ends', () => {
    const toPreorder = bookingCheck.run(bookingAnswer(201, booked('CONFIRMED', 120)));
    check.ok(
      'a CONFIRMED booking ahead goes to the pre-order and then ends',
      toPreorder.length === 1 &&
        toPreorder[0].bookingId === 'booking-1' &&
        toPreorder[0].next === 'end',
    );
  });

  const dishesCheck = node('Check the dishes');
  const dishAnswers = (...statuses) => ({
    input: statuses.map((statusCode) => ({ statusCode, body: {} })),
    nodes: { 'Compose the pre-order': [{ bookingId: 'booking-1', next: 'action' }] },
  });
  test('a dish 409 is skipped and the rest is submitted', () => {
    check.ok(
      'a dish 409 is skipped and the rest is submitted',
      dishesCheck.run(dishAnswers(200, 409, 200))[0].added === 2,
    );
  });
  test('only 409s leave nothing to submit', () => {
    check.ok('only 409s leave nothing to submit', dishesCheck.run(dishAnswers(409))[0].added === 0);
  });
  test('a dish 500 fails the run', () => {
    check.throws('a dish 500 fails the run', () => dishesCheck.run(dishAnswers(200, 500)));
  });

  const submitCheck = node('Check the submit answer');
  const submitAnswer = (statusCode) => ({
    input: [{ statusCode, body: {} }],
    nodes: { 'Check the dishes': [{ next: 'action' }] },
  });
  test('a submit 200 and 409 go on to the next step', () => {
    check.ok(
      'a submit 200 and 409 go on to the next step',
      submitCheck.run(submitAnswer(200))[0].next === 'action' &&
        submitCheck.run(submitAnswer(409))[0].next === 'action',
    );
  });
  test('a submit 500 fails the run', () => {
    check.throws('a submit 500 fails the run', () => submitCheck.run(submitAnswer(500)));
  });

  test('a menu longer than one page fails the run', () => {
    check.throws('a menu longer than one page fails the run', () =>
      node('Gather the visit').run({
        input: [{ items: dishes, total: dishes.length + 1 }],
        nodes: { 'Keep the session': [{}], 'List my bookings': [{ body: [] }] },
      }),
    );
  });
});

describe('Approved requests', () => {
  const now = Date.parse(`2026-11-20T12:00:00${TBILISI_OFFSET}`);
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
  const noteParts = node('Note the parts');
  const pickApproved = node('Pick an approved request');
  let found;
  let noted;
  before(() => {
    found = findApproved.run({ now, input: [visitWith(true)] })[0].candidates;
    noted = noteParts.run({
      input: [{ parts: [] }, { parts: [{ id: 'part-1' }] }],
      nodes: { 'Check approved requests': found },
    });
  });
  const ownConfirmed =
    'approved requests are own, confirmed, above 4 people and more than 30 minutes ahead';
  test(ownConfirmed, () => {
    check.ok(
      ownConfirmed,
      found.map(({ bookingId }) => bookingId).join() === 'open,soon-enough',
    );
  });
  test('without the approved pre-order chance no request is looked at', () => {
    check.ok(
      'without the approved pre-order chance no request is looked at',
      findApproved.run({ now, input: [visitWith(false)] })[0].candidates.length === 0,
    );
  });
  test('a request with a submitted part is skipped', () => {
    const picked = pickApproved.run({
      input: [{ items: [] }, { items: [] }],
      nodes: { 'Note the parts': noted },
    });
    check.ok(
      'a request with a submitted part is skipped',
      picked.length === 1 && picked[0].bookingId === 'open' && picked[0].next === 'action',
    );
  });
  const draftLeft =
    'a request with a draft left in its cart is skipped, and the run goes on to the action';
  test(draftLeft, () => {
    const withDraft = pickApproved.run({
      input: [{ items: [{ id: 'line-1' }] }, { items: [] }],
      nodes: { 'Note the parts': noted },
    });
    check.ok(
      draftLeft,
      withDraft.length === 1 &&
        withDraft[0].bookingId === undefined &&
        withDraft[0].next === 'action',
    );
  });
});
