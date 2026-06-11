# Configs experimentales

Una config YAML por corrida experimental. El pipeline no conoce estos
identificadores: toda la variación vive en la configuración (ver
`docs/contexto/modelos-candidatos.md`).

Convención de nombres, siguiendo la matriz experimental:

```text
y_e1_yoloe_26s_640.yaml
y_e2_yoloe_26m_640.yaml
y_e4_yoloe_26l_960.yaml
g_e1_grounding_dino_t.yaml
p_e1a_yoloe_short_prompts_25.yaml   # experimentos de estrategia de prompts
```

Cada config debe:

- componer los catálogos por referencia (`model.ref`, `source.ref`,
  `prompts.ref` — ver `configs/README.md`) y declarar **solo** las
  dimensiones bajo prueba como overrides;
- usar variantes existentes en `configs/models/` (respaldadas por
  `docs/contexto/referencias-modelos.md`; no inventar nombres);
- tener su ficha asociada en `docs/experimentos/` una vez ejecutada.
