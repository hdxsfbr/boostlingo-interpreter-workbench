/** One id per page load: names the session JSONL and the recordings folder. */
export const SESSION_ID = `${new Date().toISOString().replace(/[:.]/g, "-")}-${Math.random().toString(36).slice(2, 7)}`;
