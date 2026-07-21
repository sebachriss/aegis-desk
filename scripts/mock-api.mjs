import http from "http";
import { URL } from "url";

const PORT = 8000;
const HOST = "0.0.0.0";

const USERS = {
  "ana.garcia": { password: "ana123", role: "empleado", display_name: "Ana García" },
  "carlos.lopez": { password: "carlos123", role: "empleado", display_name: "Carlos López" },
  "admin.aegis": { password: "admin123", role: "admin", display_name: "Admin Aegis" },
};

function setCors(res, req) {
  const origin = req.headers.origin || "*";
  res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Access-Control-Allow-Credentials", "true");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization");
  res.setHeader("Vary", "Origin");
}

function parseCookies(header) {
  const cookies = {};
  if (!header) return cookies;
  for (const part of header.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    cookies[key] = rest.join("=");
  }
  return cookies;
}

function encodeUser(user) {
  return Buffer.from(JSON.stringify(user)).toString("base64");
}

function decodeUser(token) {
  try {
    const json = Buffer.from(token, "base64").toString("utf8");
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function getUserFromCookie(req) {
  const cookies = parseCookies(req.headers.cookie);
  const token = cookies["access_token"];
  if (!token) return null;
  return decodeUser(token);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function send(res, status, data) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json");
  res.end(JSON.stringify(data));
}

const server = http.createServer(async (req, res) => {
  setCors(res, req);

  if (req.method === "OPTIONS") {
    res.statusCode = 204;
    res.end();
    return;
  }

  const parsed = new URL(req.url, `http://${req.headers.host}`);
  const path = parsed.pathname;

  try {
    if (path === "/health" && req.method === "GET") {
      send(res, 200, { status: "ok", service: "aegis-desk-mock", langsmith_tracing: false });
      return;
    }

    if (path === "/login" && req.method === "POST") {
      const body = JSON.parse(await readBody(req) || "{}");
      const userEntry = USERS[body.username];
      if (!userEntry || userEntry.password !== body.password) {
        send(res, 401, { detail: "Usuario o contraseña incorrectos" });
        return;
      }
      const user = {
        username: body.username,
        role: userEntry.role,
        display_name: userEntry.display_name,
      };
      const token = encodeUser(user);
      res.setHeader(
        "Set-Cookie",
        `access_token=${token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=3600`
      );
      send(res, 200, {
        access_token: token,
        token_type: "bearer",
        role: user.role,
        display_name: user.display_name,
      });
      return;
    }

    if (path === "/logout" && req.method === "POST") {
      res.setHeader(
        "Set-Cookie",
        `access_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`
      );
      send(res, 200, { ok: true });
      return;
    }

    if (path === "/me" && req.method === "GET") {
      const user = getUserFromCookie(req);
      if (!user) {
        send(res, 401, { detail: "No autenticado" });
        return;
      }
      send(res, 200, user);
      return;
    }

    if (path === "/chat" && req.method === "POST") {
      const user = getUserFromCookie(req);
      if (!user) {
        send(res, 401, { detail: "No autenticado" });
        return;
      }
      send(res, 200, {
        thread_id: "mock-thread-" + Date.now(),
        intencion: "chat",
        respuesta:
          "Esta es una respuesta simulada del agente Aegis Desk. El backend real no está corriendo, así que estás viendo datos de prueba para validar la UI.",
        confidence: 0.95,
        fuentes: [
          { source: "Manual RRHH", content: "Políticas de uso y vacaciones." },
        ],
        elapsed_seconds: 1.2,
        requires_hitl: false,
      });
      return;
    }

    if (path === "/chat/stream" && req.method === "POST") {
      const user = getUserFromCookie(req);
      if (!user) {
        send(res, 401, { detail: "No autenticado" });
        return;
      }
      res.statusCode = 405;
      res.end();
      return;
    }

    if (path === "/stats" && req.method === "GET") {
      const user = getUserFromCookie(req);
      if (!user) {
        send(res, 401, { detail: "No autenticado" });
        return;
      }
      send(res, 200, {
        total: 42,
        avg_confidence: 0.87,
        avg_elapsed: 2.3,
        latency_p50: 1.8,
        latency_p95: 4.5,
        blocked: 3,
        total_retries: 1,
        by_intencion: {
          vacaciones: { count: 10, avg_confidence: 0.9 },
          ticket: { count: 15, avg_confidence: 0.85 },
          consulta: { count: 17, avg_confidence: 0.88 },
        },
        security_blocks_by_type: {
          prompt_injection: 2,
          pii: 1,
        },
        hitl_queue: {},
        requests_per_hour: [
          { hour: "09:00", count: 4 },
          { hour: "10:00", count: 7 },
          { hour: "11:00", count: 5 },
          { hour: "12:00", count: 9 },
          { hour: "13:00", count: 6 },
        ],
      });
      return;
    }

    if (path === "/hitl/pending" && req.method === "GET") {
      const user = getUserFromCookie(req);
      if (!user || user.role !== "admin") {
        send(res, 403, { detail: "No tienes permisos de admin" });
        return;
      }
      send(res, 200, []);
      return;
    }

    const approveMatch = path.match(/^\/hitl\/([^/]+)\/approve$/);
    if (approveMatch && req.method === "POST") {
      const user = getUserFromCookie(req);
      if (!user || user.role !== "admin") {
        send(res, 403, { detail: "No tienes permisos de admin" });
        return;
      }
      const threadId = approveMatch[1];
      send(res, 200, {
        thread_id: threadId,
        decision: "approved",
        respuesta: "Acción aprobada (mock).",
      });
      return;
    }

    const rejectMatch = path.match(/^\/hitl\/([^/]+)\/reject$/);
    if (rejectMatch && req.method === "POST") {
      const user = getUserFromCookie(req);
      if (!user || user.role !== "admin") {
        send(res, 403, { detail: "No tienes permisos de admin" });
        return;
      }
      const threadId = rejectMatch[1];
      send(res, 200, {
        thread_id: threadId,
        decision: "rejected",
        respuesta: "Acción rechazada (mock).",
      });
      return;
    }

    res.statusCode = 404;
    res.end();
  } catch (err) {
    console.error(err);
    send(res, 500, { detail: "Error interno del mock" });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Mock API corriendo en http://${HOST}:${PORT}`);
});
