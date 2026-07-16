"use client";

import { useQuery } from "@tanstack/react-query";
import { getStats, type Stats } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Activity, Clock, TrendingUp, ShieldX, RotateCcw, Zap } from "lucide-react";
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
} from "recharts";

export default function MetricsPage() {
  const { data: stats, isLoading } = useQuery<Stats>({
    queryKey: ["stats-metrics"],
    queryFn: getStats,
    refetchInterval: 15000,
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

  if (!stats) return null;

  const intentionData = Object.entries(stats.by_intencion || {}).map(([name, data]) => ({
    name,
    count: data.count,
    confidence: Math.round(data.avg_confidence * 100),
    fill: `var(--chart-${(Object.keys(stats.by_intencion).indexOf(name) % 4) + 1})`,
  }));

  const confidenceScore = Math.round(stats.avg_confidence * 100);

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Métricas</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Observabilidad del sistema multi-agente
        </p>
      </div>

      {/* Top stats */}
      <div className="grid gap-4 md:grid-cols-3">
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
        </CardContent>
      </Card>
    </div>
  );
}
