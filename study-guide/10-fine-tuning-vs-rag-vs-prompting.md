# 10. Fine-tuning vs RAG vs Prompting (teoría — NO implementado en Aegis Desk)

> **Nota honesta**: Aegis Desk no usa fine-tuning en ninguna parte. Todo el "conocimiento" y
> comportamiento del sistema viene de (a) prompts de sistema bien diseñados por nodo, (b) RAG
> sobre documentos, y (c) modelos base/instruct usados vía API (DeepInfra, Groq) sin
> reentrenamiento. Esto es importante decirlo tal cual en la entrevista si te preguntan — es
> mejor mostrar que entiendes CUÁNDO fine-tuning tendría sentido (y por qué no lo necesitaste
> aquí) que inventar que sí lo usaste.

## Concepto: las tres formas de "adaptar" un LLM a tu caso de uso

### 1. Prompting (incluye few-shot)
Modificar solo el texto de entrada: instrucciones, ejemplos, formato deseado. No cambia los
pesos del modelo.
- **Ventajas**: gratis, instantáneo, fácil de iterar, no requiere datos de entrenamiento.
- **Límites**: la ventana de contexto es finita; el modelo no "aprende" un estilo/comportamiento
  de forma robusta y consistente si el prompt es complejo; cada llamada paga el costo de tokens
  del prompt completo otra vez.
- Es lo que usa Aegis Desk en el 100% de sus nodos (supervisor, workers, crítico, juez).

### 2. RAG (Retrieval-Augmented Generation)
No modifica el modelo; le da **acceso a información externa** en tiempo de inferencia.
- **Cuándo usarlo**: el conocimiento necesario (a) cambia frecuentemente, (b) es específico de
  una organización/dominio y no está en los datos de entrenamiento del modelo base, (c) necesitas
  trazabilidad/citación de la fuente.
- **Límites**: no cambia el *comportamiento* o *estilo* del modelo, solo el conocimiento
  disponible. Sigue habiendo un límite de cuánto contexto puedes meter por llamada.
- Es lo que usa Aegis Desk para políticas de RRHH, FAQ, manuales (ver archivo 2).

### 3. Fine-tuning
Reentrenar (parcial o totalmente) los pesos del modelo sobre un dataset propio.
- **Full fine-tuning**: actualiza todos los pesos del modelo. Muy costoso en cómputo/memoria para
  modelos grandes, y requiere guardar una copia completa del modelo por cada versión fine-tuneada.
- **PEFT (Parameter-Efficient Fine-Tuning)** — la familia de técnicas modernas más usada:
  - **LoRA (Low-Rank Adaptation)**: en vez de actualizar la matriz de pesos completa de cada capa,
    se entrenan dos matrices de bajo rango (`A` y `B`) cuyo producto aproxima el delta de pesos
    necesario. Reduce drásticamente los parámetros entrenables (a menudo <1% del modelo) y por
    tanto memoria/cómputo, sin sacrificar mucha calidad en tareas específicas.
  - **QLoRA**: LoRA + el modelo base cuantizado (ej. a 4 bits) durante el entrenamiento — permite
    fine-tunear modelos grandes en GPUs de consumo con una fracción de la VRAM que requeriría
    full fine-tuning.
  - **Adapters, prefix-tuning**: variantes del mismo principio general (congelar el modelo base,
    entrenar un número pequeño de parámetros adicionales).
- **Cuándo SÍ tiene sentido fine-tuning**:
  - Necesitas un **formato/estilo de salida muy consistente y específico** que el prompting no
    logra de forma confiable a través de miles de casos variados (ej. seguir un formato JSON
    exacto en un dominio muy idiosincrático, o un tono de marca muy particular).
  - Necesitas **reducir latencia/costo** moviendo comportamiento del prompt (que se paga en
    tokens cada llamada) a los pesos del modelo, especialmente para tareas de alto volumen y baja
    complejidad (clasificación con muchas categorías finas, extracción estructurada muy
    específica).
  - Necesitas que el modelo **aprenda un patrón de razonamiento o comportamiento** que no se
    puede describir bien en un prompt (ej. imitar el estilo de decisión de expertos humanos a
    partir de miles de ejemplos etiquetados).
  - Tienes un **modelo pequeño** que quieres especializar para una tarea acotada y así evitar
    pagar por un modelo grande en producción (fine-tune un modelo chico para que rinda como uno
    grande *en esa tarea específica*).
  - **NO** es la herramienta correcta para "que el modelo sepa hechos/datos actualizados de mi
    empresa" — eso es RAG. Fine-tuning es malo para inyectar conocimiento factual actualizable
    (el conocimiento queda "congelado" en los pesos en el momento del entrenamiento, y no puedes
    citar la fuente ni actualizarlo sin reentrenar).

## Por qué Aegis Desk no necesitó fine-tuning

- El "conocimiento" (políticas de RRHH, FAQ) cambia y necesita trazabilidad → RAG, no
  fine-tuning.
- El comportamiento de clasificación (supervisor) y evaluación (crítico) se logró de forma
  suficientemente confiable con structured output + prompting + un modelo relativamente pequeño
  (Llama-3.1-8B) — no hubo necesidad de "enseñarle" el formato porque function calling ya
  garantiza el schema (no depende de que el modelo "memorice" un formato de texto).
- El volumen del proyecto (proyecto de aprendizaje, no producción a escala) no justifica el
  costo/tiempo de curar un dataset de fine-tuning y mantener un pipeline de entrenamiento.
- Es una decisión de diseño correcta: **empezar con prompting + RAG, y solo mover a fine-tuning
  si mediste (con evals) un techo de calidad/costo/latencia que el prompting no puede resolver.**
  Fine-tuning sin haber agotado antes las opciones más baratas es una señal de sobre-ingeniería.

## Preguntas de entrevista

**P: ¿Usaste fine-tuning en tu proyecto? ¿Por qué sí o por qué no?**
> No. Todo el comportamiento del sistema viene de prompting (system prompts por nodo) + RAG para
> conocimiento documental + structured output vía function calling para garantizar formato. No
> lo necesité porque el conocimiento cambia frecuentemente (mejor resuelto con RAG, con
> trazabilidad de fuente) y el comportamiento de clasificación/extracción ya es suficientemente
> confiable con function calling, sin depender de que el modelo "memorice" un formato. Fine-tuning
> tendría sentido si, por ejemplo, tuviera un volumen altísimo de clasificaciones donde quisiera
> mover el costo de un prompt largo a los pesos de un modelo chico especializado, o si necesitara
> un estilo de output muy idiosincrático que el prompting no logra de forma consistente.

**P: ¿Cuándo elegirías fine-tuning sobre RAG?**
> Cuando el problema no es "el modelo no sabe este dato", sino "el modelo no se comporta/no
> formatea/no razona de la forma que necesito" de manera consistente a través de miles de casos
> variados, y el prompting no lo logra de forma confiable. RAG resuelve falta de *conocimiento*
> actualizable con trazabilidad; fine-tuning resuelve falta de *comportamiento/estilo/patrón*
> consistente. No son mutuamente excluyentes — muchos sistemas de producción usan ambos: un
> modelo fine-tuneado para un comportamiento base, más RAG para inyectar conocimiento actual.

**P: Explícame LoRA/QLoRA en términos simples.**
> En full fine-tuning actualizas todos los pesos del modelo, lo cual es carísimo en memoria y
> cómputo para modelos grandes. LoRA congela los pesos originales y en vez de eso entrena dos
> matrices pequeñas de "bajo rango" por capa, cuyo producto aproxima el ajuste que necesitarías
> hacerle a los pesos originales — entrenas muchísimos menos parámetros (a veces <1% del total),
> lo cual reduce memoria y tiempo de entrenamiento drásticamente, con una pérdida de calidad
> generalmente pequeña para la tarea específica. QLoRA añade cuantización del modelo base
> (ej. a 4 bits) durante el entrenamiento, permitiendo fine-tunear modelos grandes en hardware
> mucho más modesto (una sola GPU de consumo, en vez de un cluster).

**P: ¿Fine-tuning "enseña" hechos nuevos al modelo de forma confiable?**
> No de forma confiable ni auditable. El modelo puede "aprender" patrones estadísticos del
> dataset de fine-tuning, pero no hay garantía de que recuerde un hecho específico con precisión,
> y no puedes citar de dónde vino esa respuesta como sí puedes con RAG. Para conocimiento
> factual que necesita ser preciso, actualizable, y trazable, RAG es la herramienta correcta;
> fine-tuning es mejor para comportamiento/estilo/formato, no para "memoria factual" fiable.
