# Debug del loop de login - Aegis Desk

## Contexto

- Proyecto: `c:\Users\Seba\Documents\Github\aegis-desk`
- Frontend: Next.js 16 + React 19 + Turbopack (`frontend/`)
- Backend real: FastAPI (no pudo levantarse por falta de `.env` y DLL de `xxhash` bloqueada en Windows)
- Se creó un **mock API** en Node.js para simular el backend y poder probar la UI.

## Objetivo

Resolver el problema donde, tras loguearse exitosamente (aparece el toast verde de bienvenida), la aplicación vuelve a cargar el login. Esto indica que la sesión no persiste: la cookie `HttpOnly` `access_token` no se envía en las siguientes requests o el `AuthContext` no reconoce al usuario.

## Cambios aplicados en esta sesión

### 1. Mock API
- **Archivo:** `scripts/mock-api.mjs`
- Simula endpoints del backend real:
  - `POST /login`
  - `POST /logout`
  - `GET /me`
  - `GET /health`
  - `POST /chat` (stream)
  - `GET /stats`
  - `GET /hitl`
  - `POST /hitl/{id}/approve` / `reject`
- Usuarios demo:
  - `ana.garcia` / `ana123` → empleado
  - `carlos.lopez` / `carlos123` → empleado
  - `admin.aegis` / `admin123` → admin
- Al hacer login devuelve `Set-Cookie: access_token=<jwt-base64>; Path=/; HttpOnly; SameSite=Lax; Max-Age=3600`.
- Los endpoints protegidos leen `access_token` de la cookie y devuelven 401 si no está.

### 2. Next.js rewrites / proxy local
- **Archivo:** `frontend/next.config.ts`
- Se agregaron dos cosas:
  - `allowedDevOrigins: ["127.0.0.1", "localhost"]` para permitir el browser preview del IDE.
  - `rewrites` para redirigir `/api/:path*` a `http://127.0.0.1:8000/:path*`, haciendo que las llamadas al API sean **mismo origen** para el navegador y evitando problemas de CORS/cookies.

```ts
const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://127.0.0.1:8000/:path*",
      },
    ];
  },
};
```

### 3. Variable de entorno frontend
- Se eliminó caché `.next/`.
- Se configuró `NEXT_PUBLIC_API_URL=/api` para que el frontend llame a rutas relativas y pasen por el proxy.
- El bundle confirmó que `API_URL` quedó como `"/api"` (con fallback `"http://localhost:8000"`).

### 4. Ajustes menores de UI
- `button.tsx`, `input.tsx`, `globals.css`, `login/page.tsx`, `chat/page.tsx`, `sidebar.tsx` (mejoras de accesibilidad y feedback táctil).
- **No son causa del problema de login**.

## Verificaciones que funcionaron

### Desde fuera del navegador
- `curl`/Python `urllib` al mock API directo (`127.0.0.1:8000`) loguean, reciben `Set-Cookie` y `/me` devuelve el usuario.
- Python `urllib` a través del proxy del preview (`127.0.0.1:3000/api/login`) también recibe la cookie y `/api/me` la usa correctamente.
- `GET /api/stats` a través del proxy responde 200 con la cookie.
- El bundle de Next.js usa `API_URL = "/api"`.

### Desde el navegador (Chrome headless)
- Se automatizó el flujo completo con Chrome headless vía Chrome DevTools Protocol:
  - Cargar `http://127.0.0.1:3000/login`.
  - Click en el botón de demo `admin.aegis` para autocompletar usuario/contraseña.
  - Submit del formulario.
- Resultado observado:
  - `POST /api/login` → 200 con `Set-Cookie: access_token` (HttpOnly).
  - `GET /api/stats` → 200, enviando la cookie automáticamente.
  - Redirección a `/dashboard` con el texto `Dashboard` y `Admin Aegis` visible.

## Causa raíz identificada y resolución

El loop de login ocurría porque la cookie `SameSite=Lax` seteada desde `127.0.0.1:8000` no se envía si el frontend se abre desde un origen cruzado (`localhost:3000` vs `127.0.0.1:8000`, o viceversa). La solución fue:

1. Usar el **proxy `/api`** de Next.js para que el navegador vea todas las llamadas al API desde el mismo origen (`127.0.0.1:3000`).
2. Setear `NEXT_PUBLIC_API_URL=/api` **sin espacios** y sin comillas (en PowerShell `$env:NEXT_PUBLIC_API_URL="/api"`; en cmd `set NEXT_PUBLIC_API_URL=/api`).
3. **Borrar `frontend/.next/`** antes de levantar el dev server cuando se cambia esta variable; de lo contrario Turbopack puede servir un bundle cacheado con un valor viejo (en este caso se observó que generaba URLs como `/api%20/me`, resolviendo en 404).
4. Abrir el browser preview exactamente en `http://127.0.0.1:3000` para que sea same-site con la cookie.

## Problemas encontrados durante la verificación

- **Caché `.next/` con valor incorrecto:** tras varios intentos, el bundle servía `API_URL` como `/api ` (con espacio al final), lo que hacía que `fetch` llamara a `/api%20/me` y `/api%20/login`, devolviendo 404 y provocando el loop.
- **Tras borrar `frontend/.next/` y reiniciar con `NEXT_PUBLIC_API_URL=/api` limpio**, el flujo se resolvió.

## Estado final

- **Resuelto.** Login exitoso, sesión persistente, redirección a `/dashboard` y carga de métricas sin bucles.
- Mock API corriendo en `127.0.0.1:8000`.
- Frontend corriendo en `127.0.0.1:3000`.

## Archivos temporales

- Eliminados:
  - `frontend/public/test-cookie.html`
  - `frontend/cookies.txt`
  - `frontend/cookies2.txt`

## Pasos confirmados para levantar el entorno de prueba

### 1. Limpiar procesos (si quedaron colgados)

```powershell
Get-NetTCPConnection -LocalPort 8000,3000 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### 2. Borrar caché de Next.js

```powershell
Remove-Item -Recurse -Force "C:\Users\Seba\Documents\Github\aegis-desk\frontend\.next"
```

### 3. Levantar mock API en background

```powershell
cd C:\Users\Seba\Documents\Github\aegis-desk
node scripts/mock-api.mjs
```

### 4. Levantar frontend en background

```powershell
cd C:\Users\Seba\Documents\Github\aegis-desk\frontend
$env:NEXT_PUBLIC_API_URL="/api"
npm run dev
```

Si se usa `cmd`:

```cmd
cd C:\Users\Seba\Documents\Github\aegis-desk\frontend
set NEXT_PUBLIC_API_URL=/api
npm run dev
```

### 5. Abrir browser preview

Usar `http://127.0.0.1:3000` (o el Local URL que muestre Next.js). No usar `localhost` si el preview está en `127.0.0.1`, para mantener same-site.

### 6. Probar login

- Ir a `/login`.
- Usar `admin.aegis` / `admin123`.
- Abrir DevTools → **Network** y **Application > Cookies**.
- Verificar que tras `POST /api/login` aparezca la cookie `access_token` con `HttpOnly`.
- Verificar que `GET /api/me` y `GET /api/stats` la incluyan en el header `Cookie:`.
- Si `/api/stats` devuelve 401, la cookie no se está enviando: revisar el origen/puerto exacto y el valor de `NEXT_PUBLIC_API_URL`.

### 7. Notas importantes

- No tocar `.env` secretos; el backend real sigue sin levantarse por `xxhash` y falta de credenciales.
- Si el problema persiste con `/api`, otra alternativa es hacer que `api.ts` use el `access_token` devuelto en el body del login y lo guarde en `localStorage` para enviarlo como `Authorization: Bearer <token>`. Esto evita depender de cookies, pero cambia el mecanismo de auth y debe revertirse si se vuelve al backend real con HttpOnly.

## Archivos clave para revisar si el problema sigue

- `frontend/src/lib/api.ts` — cliente HTTP, `credentials: "include"`.
- `frontend/src/lib/auth-context.tsx` — estado de sesión, `getMe` al inicio, `emitUnauthorized`.
- `frontend/src/app/(protected)/layout.tsx` — redirección a `/login` si no hay usuario.
- `frontend/src/app/(protected)/dashboard/page.tsx` — llama a `getStats` que puede disparar 401 y forzar logout.
- `scripts/mock-api.mjs` — lógica de cookies y CORS.
- `frontend/next.config.ts` — rewrites y `allowedDevOrigins`.

---
*Documento actualizado tras resolución del loop de login.*
