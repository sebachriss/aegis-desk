"use client";

import { useQuery } from "@tanstack/react-query";
import { getStats, ApiError, type Stats } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, Clock, TrendingUp, ShieldX, RotateCcw, Zap, ShieldAlert, Hourglass, AlertCircle } from "lucide-react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  RadialBarChart,
  RadialBar,
  PolarAngleAxis,
  LineChart,
  Line,
} from "recharts";

export default function MetricsPage() {
  const { data: stats, isLoading, error } = useQuery<Stats>({
    queryKey: ["stats-metrics"],
    queryFn: getStats,
    refetchInterval: (query) => (query.state.error ? false : 5000),
    retry: (failureCount, error) => {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) return false;
      return failureCount < 2;
    },
  });

  if (isLoading) {
    return (
      <div className="p-8 space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-4 md:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
        <Skeleton className="h-80" />
      </div>
    );
  }

  if (error) {
    const is403 = error instanceof ApiError && error.status === 403;
    return (
      <div className="p-8">
        <div className="rounded-md border border-destructive/50 bg-destructive/5 p-6 flex items-start gap-4">
          <AlertCircle className="h-6 w-6 text-destructive shrink-0 mt-0.5" />
          <div>
            <h2 className="text-lg font-semibold text-destructive">{is403 ? "Acceso denegado" : "Error"}</h2>
            <p className="text-muted-foreground mt-1">
              {is403
                ? "Las métricas requieren rol de administrador."
                : error instanceof Error
                  ? error.message
                  : "No se pudieron cargar las métricas."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (!stats) return null;

  const intentionData = Object.entries(stats.by_intencion || {}).map(([name, data]) => ({
    name,
    count: data.count,
    confidence: Math.round(data.avg_confidence * 100),
    avgElapsed: data.avg_elapsed ?? 0,
    p50: data.latency_p50 ?? 0,
    fill: `var(--chart-${(Object.keys(stats.by_intencion).indexOf(name) % 4) + 1})`,
  }));

  const confidenceScore = Math.round(stats.avg_confidence * 100);

  const hourlyData = (stats.requests_per_hour || []).map((h) => ({
    ...h,
    shortHour: h.hour.slice(11, 16),
  }));

  const securityBlocks = Object.entries(stats.security_blocks_by_type || {});
  const hitlQueue = Object.entries(stats.hitl_queue || {});

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Métricas</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Observabilidad del sistema multi-agente
        </p>
      </div>

      {/* Top stats */}
      <div className="grid gap-4 md:grid-cols-4">
        <Card className="border-blue-500/20">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Total ejecuciones</CardTitle>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-500/10 text-blue-500 dark:text-blue-400">
              <Activity className="h-4 w-4" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold tabular-nums text-blue-600 dark:text-blue-400">{stats.total}</div>
          </CardContent>
        </Card>

        <Card className="border-amber-500/20">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Reintentos</CardTitle>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-500/10 text-amber-500 dark:text-amber-400">
              <RotateCcw className="h-4 w-4" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold tabular-nums text-amber-600 dark:text-amber-400">{stats.total_retries || 0}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {stats.total > 0 ? `${((stats.total_retries / stats.total) * 100).toFixed(1)}% del total` : "—"}
            </p>
          </CardContent>
        </Card>

        <Card className="border-rose-500/20">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Bloqueadas</CardTitle>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-rose-500/10 text-rose-500 dark:text-rose-400">
              <ShieldX className="h-4 w-4" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold tabular-nums text-rose-600 dark:text-rose-400">{stats.blocked || 0}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {stats.total > 0 ? `${((stats.blocked / stats.total) * 100).toFixed(1)}% del total` : "—"}
            </p>
          </CardContent>
        </Card>

        <Card className="border-emerald-500/20">
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">Latencia p95</CardTitle>
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-500 dark:text-emerald-400">
              <Clock className="h-4 w-4" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold tabular-nums text-emerald-600 dark:text-emerald-400">{(stats.latency_p95 || 0).toFixed(2)}s</div>
            <p className="text-xs text-muted-foreground mt-1">p50: {(stats.latency_p50 || 0).toFixed(2)}s</p>
          </CardContent>
        </Card>
      </div>

      {/* Charts */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Confidence radial */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Confidence promedio</CardTitle>
            <CardDescription>Calidad global del sistema</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={250}>
              <RadialBarChart
                innerRadius="60%"
                outerRadius="100%"
                data={[{ name: "confidence", value: confidenceScore, fill: "var(--chart-3)" }]}
                startAngle={90}
                endAngle={-270}
              >
                <PolarAngleAxis type="number" domain={[0, 100]} angleAxisId={0} tick={false} />
                <RadialBar background dataKey="value" cornerRadius={8} />
                <text x="50%" y="50%" textAnchor="middle" dominantBaseline="middle" className="fill-foreground text-3xl font-bold">
                  {confidenceScore}%
                </text>
              </RadialBarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Bar chart per intention */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Casos por intención</CardTitle>
            <CardDescription>Volumen de consultas por tipo</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={intentionData}>
                <defs>
                  <linearGradient id="countGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--chart-2)" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="var(--chart-2)" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="name" className="text-xs" />
                <YAxis className="text-xs" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--popover)",
                    border: "1px solid var(--border)",
                    borderRadius: "8px",
                  }}
                />
                <Area
                  type="monotone"
                  dataKey="count"
                  stroke="var(--chart-2)"
                  fill="url(#countGradient)"
                  strokeWidth={2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Requests per hour */}
      {hourlyData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Requests por hora (últimas 24h)</CardTitle>
            <CardDescription>Volumen de tráfico en el último día</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={250}>
              <LineChart data={hourlyData}>
                <CartesianGrid strokeDasharray="3 3" className="stroke-muted" />
                <XAxis dataKey="shortHour" className="text-xs" />
                <YAxis className="text-xs" />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--popover)",
                    border: "1px solid var(--border)",
                    borderRadius: "8px",
                  }}
                />
                <Line type="monotone" dataKey="count" stroke="var(--chart-1)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Security blocks and HITL queue */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <ShieldAlert className="h-4 w-4" />
              Bloqueos por tipo
            </CardTitle>
            <CardDescription>Clasificación de bloqueos del security node</CardDescription>
          </CardHeader>
          <CardContent>
            {securityBlocks.length > 0 ? (
              <div className="space-y-2">
                {securityBlocks.map(([type, count]) => (
                  <div key={type} className="flex items-center justify-between text-sm">
                    <span className="capitalize text-muted-foreground">{type.replace(/_/g, " ")}</span>
                    <span className="font-bold tabular-nums">{count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No hay bloqueos registrados.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Hourglass className="h-4 w-4" />
              Cola HITL
            </CardTitle>
            <CardDescription>Estado de las aprobaciones pendientes</CardDescription>
          </CardHeader>
          <CardContent>
            {hitlQueue.length > 0 ? (
              <div className="space-y-2">
                {hitlQueue.map(([status, count]) => (
                  <div key={status} className="flex items-center justify-between text-sm">
                    <span className="capitalize text-muted-foreground">{status}</span>
                    <span className="font-bold tabular-nums">{count}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No hay datos de HITL.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Performance */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Rendimiento</CardTitle>
          <CardDescription>Métricas de tiempo y eficiencia</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Clock className="h-3.5 w-3.5" />
                Tiempo promedio
              </div>
              <div className="text-xl font-bold tabular-nums">{stats.avg_elapsed.toFixed(2)}s</div>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <TrendingUp className="h-3.5 w-3.5" />
                Confidence
              </div>
              <div className="text-xl font-bold tabular-nums">{(stats.avg_confidence * 100).toFixed(1)}%</div>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Zap className="h-3.5 w-3.5" />
                Success rate
              </div>
              <div className="text-xl font-bold tabular-nums">
                {stats.total > 0 ? `${(((stats.total - (stats.blocked || 0)) / stats.total) * 100).toFixed(1)}%` : "—"}
              </div>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <RotateCcw className="h-3.5 w-3.5" />
                Retry rate
              </div>
              <div className="text-xl font-bold tabular-nums">
                {stats.total > 0 ? `${((stats.total_retries / stats.total) * 100).toFixed(1)}%` : "—"}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 pt-4 border-t">
            <div className="space-y-1">
              <div className="text-xs text-muted-foreground">Latencia p50</div>
              <div className="text-xl font-bold tabular-nums">{(stats.latency_p50 || 0).toFixed(2)}s</div>
            </div>
            <div className="space-y-1">
              <div className="text-xs text-muted-foreground">Latencia p95</div>
              <div className="text-xl font-bold tabular-nums">{(stats.latency_p95 || 0).toFixed(2)}s</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
