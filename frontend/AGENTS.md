<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.

## Aegis Desk Frontend

- Next.js 16 + React 19 + shadcn/ui + Tailwind 4.
- Auth vía cookie `HttpOnly` (`access_token`) devuelta por `/login`.
- HITL, chat, dashboard y métricas consumen la API FastAPI en `src/lib/api.ts`.
- Ver `frontend/README.md` para comandos y convenciones.
<!-- END:nextjs-agent-rules -->
