"""Test de latencia del grafo completo con Groq (supervisor + crítico) + DeepInfra (workers)."""

import time
import requests


def main():
    r = requests.post(
        "http://localhost:8000/login",
        json={"username": "admin.aegis", "password": "admin123"},
    )
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    queries = [
        "hola",
        "cuantos dias de vacaciones tengo?",
        "cuantos empleados hay?",
        "listar mis tickets",
    ]

    print("=== GROQ (supervisor+critico) + DEEPINFRA (workers) ===\n")
    for q in queries:
        start = time.time()
        r2 = requests.post("http://localhost:8000/chat", json={"query": q}, headers=h)
        elapsed = time.time() - start
        if r2.status_code == 200:
            data = r2.json()
            print(f"{q:40s} | {elapsed:.2f}s | hitl={data['requires_hitl']} | {data['respuesta'][:60]}")
        else:
            print(f"{q:40s} | ERROR {r2.status_code} | {r2.text[:80]}")


if __name__ == "__main__":
    main()
