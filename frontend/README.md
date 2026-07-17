# Aegis Desk — Frontend

Frontend de Aegis Desk construido con **Next.js 16**, **React 19**, **shadcn/ui** y **Tailwind 4**.

## Rutas

- `/login` — Inicio de sesión (JWT en cookie `HttpOnly`).
- `/chat` — Chat con el agente multi-agente.
- `/hitl` — Aprobaciones pendientes (solo admin).
- `/dashboard` — Dashboard resumido.
- `/metrics` — Métricas detalladas de trazas.

## Setup

```bash
cd frontend
npm install
npm run dev
```

Abrir [http://localhost:3000](http://localhost:3000).

## Auth

El frontend no guarda el token en `localStorage`. Después de `/login` la API devuelve una cookie `HttpOnly` llamada `access_token`. Cada request a endpoints protegidos envía la cookie automáticamente.

## Comandos

| Comando | Propósito |
|---|---|
| `npm run dev` | Modo desarrollo con Turbopack |
| `npm run build` | Build de producción (standalone) |
| `npm run start` | Iniciar build de producción |
| `npm run lint` | ESLint |

## Convenciones

- Next.js App Router (`app/`).
- `src/lib/api.ts` centraliza llamadas a la API FastAPI.
- `src/lib/auth-context.tsx` maneja la sesión y redirige ante `401`.
- Estados de carga, error, empty y stale manejados con React Query.

## Reglas específicas

- Este proyecto usa Next.js 16 con APIs breaking. Consultar `node_modules/next/dist/docs/` si dudas.
- No modificar `window.__addPending` ni almacenar tokens en `localStorage`.
