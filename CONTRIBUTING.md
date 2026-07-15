# Contributing — Aegis Desk

¡Gracias por tu interés en contribuir! Este es un proyecto educativo, pero todas las contribuciones son bienvenidas.

## Cómo contribuir

### Reportar bugs

1. Verifica que el bug no esté ya reportado en [Issues](https://github.com/sebachriss/aegis-desk/issues)
2. Abre un nuevo issue con el template de bug report
3. Incluye:
   - Pasos para reproducir
   - Comportamiento esperado vs actual
   - Versión de Python y OS
   - Logs relevantes (sin exponer API keys)

### Sugerir mejoras

1. Abre un issue con el template de feature request
2. Describe claramente la mejora y por qué es útil
3. Si es posible, incluye ejemplos de uso

### Enviar Pull Requests

1. Fork el repo
2. Crea una branch: `git checkout -b feature/mi-mejora`
3. Haz tus cambios siguiendo el estilo del código existente
4. Testea tus cambios:
   ```bash
   python -m evals.run_evals       # los evals deben seguir pasando
   python -m redteam.run_redteam   # red teaming debe seguir 100%
   ```
5. Commit con mensaje descriptivo:
   ```
   feat: descripción de la mejora
   fix: descripción del fix
   docs: descripción del cambio de docs
   ```
6. Push: `git push origin feature/mi-mejora`
7. Abre un PR usando el template

## Estilo de código

- **Python 3.11+**
- Type hints en todas las funciones públicas
- Docstrings en formato Google-style
- Imports al inicio del archivo
- Sin emojis en el código (solo en strings de respuesta del agente)
- Nombres de variables en español o inglés según el contexto del módulo

## Estructura del proyecto

Lee el [README.md](README.md) para entender la arquitectura antes de contribuir.

## Seguridad

- **NUNCA** commitear `.env` o API keys
- Si encuentras una vulnerabilidad de seguridad, usa el [Security Policy](SECURITY.md)
- Los nuevos tools deben ser simulados (no realizar acciones reales externas)
- Toda nueva feature que involucre acciones debe pasar por HITL

## Tests

Antes de un PR, asegúrate de que:

```bash
# Tests unitarios por fase
python scripts/test_rag.py
python scripts/test_security.py
python scripts/test_hitl.py

# Evals (deben mantener >=90% pass rate)
python -m evals.run_evals

# Red teaming (deben mantener 100% defense rate)
python -m redteam.run_redteam
```
