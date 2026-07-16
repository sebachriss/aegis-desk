"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Clock, ShieldX, TrendingUp, MessageSquare } from "lucide-react";
import { getStats, type Stats } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";

const PIE_COLORS = ["var(--chart-1)", "var(--chart-2)", "var(--chart-3)", "var(--chart-4)", "var(--chart-5)"];

const KPI_STYLES = [
  { iconBg: "bg-blue-500/10 text-blue-500 dark:text-blue-400", valueClass: "text-blue-600 dark:text-blue-400" },
  { iconBg: "bg-emerald-500/10 text-emerald-500 dark:text-emerald-400", valueClass: "text-emerald-600 dark:text-emerald-400" },
  { iconBg: "bg-amber-500/10 text-amber-500 dark:text-amber-400", valueClass: "text-amber-600 dark:text-amber-400" },
  { iconBg: "bg-rose-500/10 text-rose-500 dark:text-rose-400", valueClass: "text-rose-600 dark:text-rose-400" },
];

function KPICard({
  title,
  value,
  icon: Icon,
  description,
  colorIndex = 0,
}: {
  title: string;
  value: string | number;
  icon: React.ElementType;
  description?: string;
  colorIndex?: number;
}) {
  const style = KPI_STYLES[colorIndex % KPI_STYLES.length];
  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex flex-row items-center justify-between pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">{title}</CardTitle>
        <div className={`flex h-8 w-8 items-center justify-center rounded-lg ${style.iconBg}`}>
          <Icon className="h-4 w-4" />
        </div>
      </CardHeader>
      <CardContent>
        <div className={`text-2xl font-bold ${style.valueClass}`}>{value}</div>
        {description && <p className="text-xs text-muted-foreground mt-1">{description}</p>}
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const { data: stats, isLoading } = useQuery<Stats>({
    queryKey: ["stats"],
    queryFn: getStats,
    refetchInterval: 30000,
  });

  if (isLoading) {
    return (
      <div className="p-8 space-y-6">
        <Skeleton className="h-8 w-48" />
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-28" />
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
  }));

  const pieData = intentionData.map((d) => ({ name: d.name, value: d.count }));

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground text-sm mt-1">Métricas en tiempo real del sistema multi-agente</p>
      </div>

      {/* KPIs */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <KPICard
          title="Total ejecuciones"
          value={stats.total}
          icon={Activity}
          description="Consultas procesadas"
          colorIndex={0}
        />
        <KPICard
          title="Confidence promedio"
          value={`${(stats.avg_confidence * 100).toFixed(1)}%`}
          icon={TrendingUp}
          description="Calidad promedio de respuestas"
          colorIndex={1}
        />
        <KPICard
          title="Tiempo promedio"
          value={`${stats.avg_elapsed.toFixed(2)}s`}
          icon={Clock}
          description="Latencia por consulta"
          colorIndex={2}
        />
        <KPICard
          title="Bloqueadas"
          value={stats.blocked || 0}
          icon={ShieldX}
          description="Ataques bloqueados por security node"
          colorIndex={3}
        />
      </div>

      {/* Charts */}
      <div className="grid gap-4 md:grid-cols-2">
        {/* Bar chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Ejecuciones por intención</CardTitle>
            <CardDescription>Distribución de consultas por tipo de agente</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={intentionData}>
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
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {intentionData.map((_, index) => (
                    <Cell key={`bar-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Pie chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Distribución de intenciones</CardTitle>
            <CardDescription>Proporción de cada tipo de consulta</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={4}
                  dataKey="value"
                >
                  {pieData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: "var(--popover)",
                    border: "1px solid var(--border)",
                    borderRadius: "8px",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex flex-wrap gap-3 mt-2 justify-center">
              {pieData.map((entry, index) => (
                <div key={entry.name} className="flex items-center gap-1.5">
                  <div
                    className="h-3 w-3 rounded-full"
                    style={{ backgroundColor: PIE_COLORS[index % PIE_COLORS.length] }}
                  />
                  <span className="text-xs text-muted-foreground">{entry.name}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Detail table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Detalle por intención</CardTitle>
          <CardDescription>Métricas granulares por tipo de agente</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50">
                <tr className="border-b">
                  <th className="px-4 py-3 text-left font-medium">Intención</th>
                  <th className="px-4 py-3 text-right font-medium">Casos</th>
                  <th className="px-4 py-3 text-right font-medium">Avg Confidence</th>
                  <th className="px-4 py-3 text-left font-medium">Estado</th>
                </tr>
              </thead>
              <tbody>
                {intentionData.map((row) => (
                  <tr key={row.name} className="border-b last:border-0">
                    <td className="px-4 py-3 font-medium">{row.name}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{row.count}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{row.confidence}%</td>
                    <td className="px-4 py-3">
                      <Badge variant={row.confidence >= 80 ? "default" : row.confidence >= 60 ? "secondary" : "destructive"}>
                        {row.confidence >= 80 ? "Saludable" : row.confidence >= 60 ? "Aceptable" : "Bajo"}
                      </Badge>
                    </td>
                  </tr>
                ))}
                {intentionData.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-muted-foreground">
                      No hay datos todavía. Envía mensajes desde el Chat.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {/* Footer stats */}
      <div className="flex items-center gap-4 text-sm text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <MessageSquare className="h-4 w-4" />
          <span>Reintentos totales: <strong className="text-foreground">{stats.total_retries || 0}</strong></span>
        </div>
      </div>
    </div>
  );
}
