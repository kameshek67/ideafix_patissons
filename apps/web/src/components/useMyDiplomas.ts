"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getMaxConfig, getMyDiplomas, putMyDiplomas } from "@/lib/api";
import { type DiplomaEntry, loadLocalDiplomas, saveLocalDiplomas } from "@/lib/diplomas";
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
        await putMyDiplomas(initData, specs);
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
        if (dirty.current || (!mine.diplomas.length && current.current.length)) {
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

  return { entries, loaded, storage, sync, update };
}
