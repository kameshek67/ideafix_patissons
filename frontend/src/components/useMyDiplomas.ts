"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getMaxConfig, getMyDiplomas, putMyDiplomas } from "@/lib/api";
import { type DiplomaEntry, loadLocalDiplomas, saveLocalDiplomas } from "@/lib/diplomas";
import { cleanEge, type EgeScores, hasEge, loadLocalEge, NO_EGE, saveLocalEge } from "@/lib/ege";
import { useMax } from "./MaxProvider";

/** где живут дипломы: на этом устройстве или в профиле пользователя MAX (на сервере) */
export type DiplomaStorage = "device" | "max";
export type SyncState = "idle" | "loading" | "saving" | "saved" | "error";

/** Дипломы ученика. Копия всегда лежит на устройстве (список виден сразу), а внутри MAX
 *  с настроенным ботом главная копия — на сервере: дипломы видны на всех устройствах. */
export function useMyDiplomas() {
  const app = useMax();
  const initData = app?.initData ?? null;
  const [entries, setEntries] = useState<DiplomaEntry[]>([]);
  const [ege, setEge] = useState<EgeScores>(NO_EGE);
  const currentEge = useRef<EgeScores>(NO_EGE);
  const [loaded, setLoaded] = useState(false);
  const [storage, setStorage] = useState<DiplomaStorage>("device");
  const [sync, setSync] = useState<SyncState>("idle");

  const server = useRef(false); // сервер принимает дипломы этого пользователя
  const dirty = useRef(false); // список меняли, пока грузилась копия с сервера
  const pending = useRef<string[] | null>(null);
  const saving = useRef(false);
  const current = useRef<DiplomaEntry[]>([]);

  useEffect(() => {
    const local = loadLocalDiplomas();
    current.current = local;
    setEntries(local);
    currentEge.current = loadLocalEge();
    setEge(currentEge.current);
    setLoaded(true);
  }, []);

  const flush = useCallback(async () => {
    if (!initData || !server.current || saving.current) return;
    saving.current = true;
    while (pending.current) {
      const specs = pending.current;
      pending.current = null;
      setSync("saving");
      try {
        await putMyDiplomas(initData, specs, currentEge.current);
        setSync(pending.current ? "saving" : "saved");
      } catch {
        setSync("error");
      }
    }
    saving.current = false;
  }, [initData]);

  useEffect(() => {
    if (!initData) return;
    let alive = true;
    void (async () => {
      setSync("loading");
      try {
        if (!(await getMaxConfig()).enabled) {
          if (alive) setSync("idle");
          return;
        }
        const mine = await getMyDiplomas(initData);
        if (!alive) return;
        server.current = true;
        setStorage("max");
        const serverEge = cleanEge({ scores: mine.ege, mock: mine.ege_is_mock });
        // на устройстве есть дипломы или баллы, а в профиле MAX ещё нет — отправляем свои
        const localOnly =
          (!mine.diplomas.length && current.current.length > 0) || (!hasEge(serverEge) && hasEge(currentEge.current));
        if (dirty.current || localOnly) {
          // первый запуск в MAX с дипломами на устройстве или правки во время загрузки
          pending.current = current.current.map((d) => d.spec);
          void flush();
          return;
        }
        const list = mine.diplomas.map((d) => ({
          spec: d.spec,
          olympiad: d.olympiad_name,
          profile: d.profile_name,
        }));
        current.current = list;
        setEntries(list);
        saveLocalDiplomas(list);
        currentEge.current = serverEge;
        setEge(serverEge);
        saveLocalEge(serverEge);
        setSync("saved");
      } catch {
        if (alive) setSync("error");
      }
    })();
    return () => {
      alive = false;
    };
  }, [initData, flush]);

  const update = useCallback(
    (next: DiplomaEntry[]) => {
      dirty.current = true;
      current.current = next;
      setEntries(next);
      saveLocalDiplomas(next);
      pending.current = next.map((d) => d.spec);
      void flush();
    },
    [flush],
  );

  const updateEge = useCallback(
    (next: EgeScores) => {
      dirty.current = true;
      currentEge.current = next;
      setEge(next);
      saveLocalEge(next);
      pending.current = current.current.map((d) => d.spec);
      void flush();
    },
    [flush],
  );

  return { entries, ege, loaded, storage, sync, update, updateEge };
}
