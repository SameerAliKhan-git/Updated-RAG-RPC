import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import { EvalTrendChart } from "./EvalTrendChart";

export function SystemView() {
  const queryClient = useQueryClient();

  const health = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 15_000 });
  const evalStatus = useQuery({ queryKey: ["eval"], queryFn: api.evalStatus, refetchInterval: 10_000 });
  const evalHistory = useQuery({ queryKey: ["evalHistory"], queryFn: () => api.evalHistory(30), refetchInterval: 60_000 });

  const runEval = useMutation({
    mutationFn: api.runEval,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["eval"] }),
  });

  const services = (health.data?.services ?? {}) as Record<string, { status: string; latency_ms?: number }>;

  return (
    <div className="h-full overflow-y-auto px-4 py-6 md:px-8">
      <div className="mx-auto max-w-4xl">
        <h1 className="text-2xl font-semibold" style={{ fontFamily: "var(--font-display)" }}>
          System
        </h1>
        <p className="mt-1 text-sm" style={{ color: "var(--text-tertiary)" }}>
          Service health and answer-quality evaluation
        </p>

        {/* Health */}
        <section className="mt-8">
          <h2 className="text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>
            Services
          </h2>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {health.isLoading && <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>Checking…</p>}
            {health.error != null && (
              <div className="rounded-3xl p-4 text-sm" style={{ background: "var(--surface)", color: "var(--g-red)" }}>
                API unreachable on port 8000
              </div>
            )}
            {Object.entries(services).map(([name, svc]) => {
              const healthy = svc.status === "healthy" || svc.status === "ok";
              return (
                <div key={name} className="rounded-3xl p-4" style={{ background: "var(--surface)" }}>
                  <div className="flex items-center gap-2">
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ background: healthy ? "var(--g-green)" : "var(--g-red)" }}
                    />
                    <span className="text-sm font-medium capitalize" style={{ color: "var(--text)" }}>
                      {name}
                    </span>
                  </div>
                  <p className="mt-1.5 text-xs" style={{ color: "var(--text-tertiary)" }}>
                    {svc.status}
                    {svc.latency_ms != null ? ` · ${Math.round(svc.latency_ms)}ms` : ""}
                  </p>
                </div>
              );
            })}
          </div>
        </section>

        {/* Evaluation */}
        <section className="mt-10">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>
              RAGAS Evaluation
            </h2>
            <button
              onClick={() => runEval.mutate()}
              disabled={runEval.isPending || evalStatus.data?.status === "RUNNING"}
              className="rounded-full px-4 py-2 text-xs font-medium text-white disabled:opacity-50"
              style={{ background: "var(--gradient-gemini-solid)" }}
            >
              {evalStatus.data?.status === "RUNNING" ? "Running…" : "Run evaluation"}
            </button>
          </div>

          <div className="mt-3 rounded-3xl p-5" style={{ background: "var(--surface)" }}>
            {evalStatus.data?.status === "NOT_RUN" && (
              <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
                No evaluation has been run yet. Trigger one to score faithfulness and answer relevancy with the
                local judge model.
              </p>
            )}
            {evalStatus.data?.status === "RUNNING" && (
              <p className="gradient-shimmer text-sm font-medium">Evaluating sampled answers…</p>
            )}
            {evalStatus.data?.status === "FAILED" && (
              <p className="text-sm" style={{ color: "var(--g-red)" }}>
                Last evaluation failed — check API logs.
              </p>
            )}
            {evalStatus.data?.scores && (
              <div className="flex flex-wrap gap-6">
                <ScoreDial label="Faithfulness" value={evalStatus.data.scores.faithfulness ?? 0} />
                <ScoreDial label="Answer relevancy" value={evalStatus.data.scores.answer_relevancy ?? 0} />
                <div className="self-center text-xs leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                  <p>method: {evalStatus.data.scores.method ?? "—"}</p>
                  <p>dataset: {evalStatus.data.scores.dataset ?? "—"}</p>
                  <p>samples: {evalStatus.data.scores.sample_count ?? "—"}</p>
                  <p>as of: {evalStatus.data.timestamp?.slice(0, 19).replace("T", " ") ?? "—"}</p>
                </div>
              </div>
            )}
          </div>
        </section>

        {/* Quality trend */}
        <section className="mt-10">
          <h2 className="text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>
            Answer Quality Trend
          </h2>
          <div className="mt-3 rounded-3xl p-5" style={{ background: "var(--surface)" }}>
            <EvalTrendChart history={evalHistory.data?.history ?? []} />
          </div>
        </section>

        <section className="mt-10">
          <h2 className="text-sm font-semibold" style={{ color: "var(--text-secondary)" }}>
            Observability
          </h2>
          <div className="mt-3 flex flex-wrap gap-3 text-sm">
            <ExternalCard label="Grafana dashboards" href="http://localhost:3002" />
            <ExternalCard label="Prometheus" href="http://localhost:9092" />
            <ExternalCard label="Langfuse traces" href="http://localhost:3001" />
            <ExternalCard label="OpenSearch dashboards" href="http://localhost:5601" />
          </div>
        </section>
      </div>
    </div>
  );
}

function ScoreDial({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  const angle = value * 360;
  return (
    <div className="flex items-center gap-3">
      <div
        className="flex h-16 w-16 items-center justify-center rounded-full"
        style={{
          background: `conic-gradient(var(--g-blue) 0deg, #9b72cb ${angle * 0.6}deg, #d96570 ${angle}deg, var(--surface-2) ${angle}deg)`,
        }}
      >
        <div
          className="flex h-12 w-12 items-center justify-center rounded-full text-sm font-semibold"
          style={{ background: "var(--surface)", color: "var(--text)" }}
        >
          {pct}
        </div>
      </div>
      <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
        {label}
      </span>
    </div>
  );
}

function ExternalCard({ label, href }: { label: string; href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="rounded-full px-4 py-2 text-sm transition-all hover:shadow-md"
      style={{ background: "var(--surface)", color: "var(--text-secondary)" }}
    >
      {label} ↗
    </a>
  );
}
