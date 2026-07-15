## Descripción

Descripción clara de los cambios en este PR.

## Tipo de cambio

- [ ] Bug fix (cambio que no rompe nada y fixea un issue)
- [ ] Feature nueva (cambio que añade funcionalidad)
- [ ] Breaking change (fix o feature que rompe compatibilidad)
- [ ] Documentación
- [ ] Seguridad

## Checklist

- [ ] Mi código sigue el estilo del proyecto
- [ ] Hice self-review de mis cambios
- [ ] Los imports están al inicio del archivo
- [ ] No commiteé `.env` ni API keys
- [ ] Los tests pasan:
  - [ ] `python -m evals.run_evals` (>=90% pass rate)
  - [ ] `python -m redteam.run_redteam` (100% defense rate)
  - [ ] Tests de la fase afectada
- [ ] Actualicé la documentación si fue necesario

## Issue relacionado

Closes #(número de issue)
