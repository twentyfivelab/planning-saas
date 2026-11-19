/** File d'enregistrement automatique : une seule requête à la fois, les modifications faites pendant un envoi partent dans le suivant,
 *  « Enregistré » seulement quand le serveur a confirmé TOUTES les modifications, et une erreur garde les modifications non enregistrées
 *  pour « Réessayer ». Indépendant de React (testé seul). */
export type SaveState = "idle" | "saving" | "saved" | "error" | "stopped";

export class SaveQueue<K, V> {
  private pending = new Map<K, V>();
  private inflight: Map<K, V> | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  state: SaveState = "idle";
  error = "";
  /** Nombre d'enregistrements confirmés par le serveur (permet d'attendre une confirmation RÉELLE, jamais un état précédent). */
  confirmed = 0;

  /** `isFinal` : erreur définitive (ex. planning supprimé entre-temps) ; la file s'arrête, plus aucun envoi ni « Réessayer ». */
  constructor(private send: (batch: Map<K, V>) => Promise<void>, private onChange: () => void, private delay = 350,
              private isFinal: (e: unknown) => boolean = () => false) {}

  /** Une modification à enregistrer (la plus récente l'emporte pour une même clé). */
  set(key: K, value: V): void {
    if (this.state === "stopped") return; // plus rien n'est envoyé pour une ressource qui n'existe plus
    this.pending.set(key, value);
    this.mark("saving");
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.flush(), this.delay);
  }

  /** Vrai tant qu'une modification n'est pas confirmée par le serveur (en attente ou en cours d'envoi). */
  get unsaved(): boolean {
    return this.pending.size > 0 || this.inflight !== null;
  }

  async flush(): Promise<void> {
    if (this.inflight || !this.pending.size) return;
    const batch = this.pending;
    this.pending = new Map();
    this.inflight = batch;
    try {
      await this.send(batch);
      this.inflight = null;
      if (this.pending.size) return this.flush(); // modifications arrivées pendant l'envoi : enregistrées à leur tour
      this.confirmed += 1;
      this.mark("saved");
    } catch (e) {
      this.inflight = null;
      if (this.isFinal(e)) {
        this.pending.clear(); clearTimeout(this.timer);
        this.error = e instanceof Error ? e.message : String(e);
        this.state = "stopped"; this.onChange();
        return;
      }
      for (const [k, v] of batch) if (!this.pending.has(k)) this.pending.set(k, v); // rien n'est perdu : prêt pour « Réessayer »
      this.error = e instanceof Error ? e.message : String(e);
      this.mark("error");
    }
  }

  retry(): void {
    if (this.state === "stopped") return;
    clearTimeout(this.timer);
    this.mark("saving");
    void this.flush();
  }

  dispose(): void {
    clearTimeout(this.timer);
  }

  private mark(s: SaveState): void {
    if (this.state === "stopped") return;
    this.state = s;
    if (s !== "error") this.error = "";
    this.onChange();
  }
}
