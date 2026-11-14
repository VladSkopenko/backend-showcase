import { DEV_API } from './constants.mjs';

export const WAITER_EMAIL = 'waiter-bot@example.com';
export const CREDENTIAL = 'Booking bot password';

export const conflict = (code) => ({ statusCode: 409, body: { code, message: code } });

// A stub of the staff API with the rules the waiter meets: the list answers pending requests in the
// given order (earliest start, then oldest), one page of `limit`; approving confirms a request and
// rejects the pending ones on the same table and start; deciding a request that is no longer
// pending answers 409 REQUEST_NOT_PENDING. `answers` overrides one call, e.g. 'approve r1'.
export class StaffApi {
  constructor({ requests = [], answers = {} } = {}) {
    this.requests = requests.map((request) => ({
      status: 'PENDING',
      table: 'table-1',
      ...request,
    }));
    this.answers = answers;
    this.handle = this.handle.bind(this);
  }

  status(id) {
    return this.requests.find((request) => request.id === id).status;
  }

  handle({ method, url, headers, body, credential }) {
    const path = url.replace(DEV_API, '');
    if (method === 'POST' && path === '/auth/login') {
      if (this.answers.login) {
        return this.answers.login;
      }
      const signedIn = credential === CREDENTIAL && body?.email === WAITER_EMAIL;
      return signedIn
        ? {
            statusCode: 200,
            headers: {
              'set-cookie': ['access_token=a; HttpOnly; Path=/', 'refresh_token=r; Path=/api'],
            },
            body: {},
          }
        : { statusCode: 401, body: { code: 'INVALID_CREDENTIALS' } };
    }
    if (headers.Cookie !== 'access_token=a; refresh_token=r') {
      return { statusCode: 401, body: { code: 'NOT_AUTHENTICATED' } };
    }
    const list = path.match(/^\/staff\/booking-requests\?limit=(\d+)$/);
    if (method === 'GET' && list) {
      if (this.answers.list) {
        return this.answers.list;
      }
      const pending = this.requests.filter((request) => request.status === 'PENDING');
      const limit = Number(list[1]);
      return {
        statusCode: 200,
        body: {
          items: pending.slice(0, limit).map((request) => ({
            id: request.id,
            status: request.status,
            party_size: 6,
            starts_at: request.starts_at,
            table: { id: request.table },
          })),
          total: pending.length,
          limit,
          offset: 0,
        },
      };
    }
    const decision = path.match(/^\/staff\/booking-requests\/([^/]+)\/(approve|reject)$/);
    if (method === 'POST' && decision) {
      const [, id, action] = decision;
      const override = this.answers[`${action} ${id}`];
      if (override) {
        return override;
      }
      const request = this.requests.find((entry) => entry.id === id);
      if (!request) {
        return { statusCode: 404, body: { code: 'BOOKING_NOT_FOUND' } };
      }
      if (request.status !== 'PENDING') {
        return conflict('REQUEST_NOT_PENDING');
      }
      if (action === 'approve') {
        request.status = 'CONFIRMED';
        for (const other of this.requests) {
          const competes =
            other.status === 'PENDING' &&
            other.table === request.table &&
            other.starts_at === request.starts_at;
          if (competes) {
            other.status = 'REJECTED';
          }
        }
      } else {
        request.status = 'REJECTED';
      }
      return { statusCode: 200, body: { id, status: request.status } };
    }
    return { statusCode: 500, body: { code: 'SERVER_ERROR', message: `no stub for ${url}` } };
  }
}
