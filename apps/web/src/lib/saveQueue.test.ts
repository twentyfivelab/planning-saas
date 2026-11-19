import { describe, expect, it, vi } from "vitest";
import { SaveQueue } from "./saveQueue";

const deferred = () => { let resolve!: () => void, reject!: (e: Error) => void; const p = new Promise<void>((a, b) => { resolve = a; reject = b; }); return { p, resolve, reject }; };

describe("enregistrement automatique", () => {
  it("« Enregistré » seulement quand toutes les modifications sont confirmées, y compris celles faites pendant un envoi", async () => {
    vi.useFakeTimers();
    const calls: Map<string, boolean>[] = []; const gates: ReturnType<typeof deferred>[] = [];
    const q = new SaveQueue<string, boolean>((b) => { calls.push(new Map(b)); const g = deferred(); gates.push(g); return g.p; }, () => {}, 300);
    q.set("ana", true); q.set("ben", true);
    expect(q.state).toBe("saving");
    await vi.advanceTimersByTimeAsync(300);
    expect(calls).toHaveLength(1); // un seul envoi groupé
    q.set("cleo", false); // pendant l'envoi
    await vi.advanceTimersByTimeAsync(300);
    expect(calls).toHaveLength(1); // jamais deux envois simultanés
    gates[0].resolve(); await vi.advanceTimersByTimeAsync(0);
    expect(q.state).toBe("saving"); // la modification de Cléo n'est pas encore confirmée
    expect(calls).toHaveLength(2); expect([...calls[1]]).toEqual([["cleo", false]]);
    gates[1].resolve(); await vi.advanceTimersByTimeAsync(0);
    expect(q.state).toBe("saved"); expect(q.unsaved).toBe(false); expect(q.confirmed).toBe(1); // une confirmation pour l'ensemble
    vi.useRealTimers();
  });

  it("une erreur conserve les modifications non enregistrées ; « Réessayer » les renvoie", async () => {
    vi.useFakeTimers();
    const calls: Map<string, boolean>[] = []; let fail = true;
    const q = new SaveQueue<string, boolean>(async (b) => { calls.push(new Map(b)); if (fail) throw new Error("Réseau indisponible"); }, () => {}, 100);
    q.set("ana", true);
    await vi.advanceTimersByTimeAsync(100);
    expect(q.state).toBe("error"); expect(q.error).toBe("Réseau indisponible"); expect(q.unsaved).toBe(true);
    fail = false; q.retry(); await vi.advanceTimersByTimeAsync(0);
    expect(q.state).toBe("saved"); expect([...calls[1]]).toEqual([["ana", true]]);
    vi.useRealTimers();
  });

  it("la valeur la plus récente l'emporte pour une même clé", async () => {
    vi.useFakeTimers();
    const calls: Map<string, boolean>[] = [];
    const q = new SaveQueue<string, boolean>(async (b) => { calls.push(new Map(b)); }, () => {}, 100);
    q.set("ana", true); q.set("ana", false);
    await vi.advanceTimersByTimeAsync(100);
    expect([...calls[0]]).toEqual([["ana", false]]);
    vi.useRealTimers();
  });

  it("arrêt définitif (ressource supprimée entre-temps) : plus aucun envoi, ni nouvel essai", async () => {
    vi.useFakeTimers();
    let calls = 0;
    const q = new SaveQueue<string, boolean>(async () => { calls += 1; throw new Error("Ce planning a été supprimé"); }, () => {}, 100, (e) => String(e).includes("supprimé"));
    q.set("ana", true);
    await vi.advanceTimersByTimeAsync(100);
    expect(q.state).toBe("stopped"); expect(q.unsaved).toBe(false);
    q.set("ben", true); q.retry(); await vi.advanceTimersByTimeAsync(500);
    expect(calls).toBe(1); expect(q.state).toBe("stopped");
    vi.useRealTimers();
  });
});
