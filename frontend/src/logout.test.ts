import { describe, expect, it, vi } from "vitest";
import { logout } from "./App";

describe("logout (A16)", () => {
  it("stops the session, POSTs /auth/logout same-origin, then goes to the logged-out page", async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method} ${url} ${init?.credentials}`);
      return new Response("{}");
    });
    vi.stubGlobal("fetch", fetchMock);
    const nav = vi.fn();
    await logout(() => void calls.push("stop"), nav);
    expect(calls).toEqual(["stop", "POST /auth/logout same-origin"]);
    expect(nav).toHaveBeenCalledWith("/auth/logged-out");
  });
  it("still navigates when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    const nav = vi.fn();
    await logout(undefined, nav).catch(() => {});
    expect(nav).toHaveBeenCalledWith("/auth/logged-out");
  });
});
