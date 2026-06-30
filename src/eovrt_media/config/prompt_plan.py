"""Estructura resuelta de consumo de prompts: PromptPlan.

Reemplaza el `list[str]` plano que se pasaba a los adaptadores. Aplana las
frases de las clases activas (incluyendo sinónimos) en una lista ordenada,
donde el índice coincide con el `class_id` que devuelve YOLOE.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptPhrase:
    """Una frase concreta alimentada al modelo, ligada a su clase canónica."""

    index: int
    text: str
    prompt_id: str
    canonical: str
    strategy: str | None = None
    condition_id: str | None = None


@dataclass(frozen=True)
class PromptPlan:
    """Plan resuelto para un backend concreto."""

    set_id: str
    backend: str
    phrases: tuple[PromptPhrase, ...]

    def __post_init__(self) -> None:
        for i, p in enumerate(self.phrases):
            if p.index != i:
                raise ValueError(
                    f"PromptPlan.phrases[{i}].index == {p.index}, expected {i}; "
                    "las frases deben estar ordenadas por índice sin huecos."
                )

    def texts(self) -> list[str]:
        """Lista de frases en orden — entrada al modelo."""
        return [p.text for p in self.phrases]

    def by_index(self) -> list[PromptPhrase]:
        """Frases en orden de índice; el class_id de YOLOE indexa la lista directamente."""
        return list(self.phrases)

    def by_text(self) -> dict[str, PromptPhrase]:
        """Resolución por texto exacto (GDINO devuelve spans de texto)."""
        return {p.text: p for p in self.phrases}

    @classmethod
    def from_texts(
        cls, texts: list[str], backend: str = "default", set_id: str = "adhoc"
    ) -> PromptPlan:
        """Construye un plan trivial desde textos sueltos (warmup, tests).

        Cada texto se vuelve su propia frase con prompt_id == canonical == text.
        """
        phrases = tuple(
            PromptPhrase(index=i, text=t, prompt_id=t, canonical=t)
            for i, t in enumerate(texts)
        )
        return cls(set_id=set_id, backend=backend, phrases=phrases)
