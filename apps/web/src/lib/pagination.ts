import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

export function pageSize(value: string | null) {
  const size = Number(value);
  return [10, 20, 50].includes(size) ? size : 10;
}

export function useListPage() {
  const [params, setParams] = useSearchParams();
  const number = Number(params.get("page"));
  const page = Number.isSafeInteger(number) && number > 0 ? number : 1;
  const limit = pageSize(params.get("limit"));
  function update(key: string, value: string) {
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (value) next.set(key, value);
      else next.delete(key);
      if (key !== "page") next.delete("page");
      return next;
    });
  }
  return { params, page, limit, update };
}

export function useClampPage(
  total: number | undefined,
  page: number,
  limit: number,
) {
  const [, setParams] = useSearchParams();
  useEffect(() => {
    if (total === undefined) return;
    const last = Math.max(1, Math.ceil(total / limit));
    if (page > last)
      setParams(
        (previous) => {
          const next = new URLSearchParams(previous);
          next.set("page", String(last));
          return next;
        },
        { replace: true },
      );
  }, [total, page, limit, setParams]);
}
