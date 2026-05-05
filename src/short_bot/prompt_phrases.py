"""Localized sentinel phrases used by the generator-mode prompt."""
from __future__ import annotations


GENERATOR_PHRASES: dict[str, dict[str, str]] = {
    "tr": {
        "channel_id": "KANAL KİMLİĞİ",
        "topic": "Konu",
        "language": "Türkçe",
        "task": "GÖREV",
        "forbidden_intro": "ASLA AŞAĞIDAKİ METİNLERE BENZER ÜRETME (paraphrase dahil):",
        "forbidden_end": "─── liste sonu ───",
        "topic_rotation": "TEMA ROTASYONU (son 7 gün)",
        "output_intro": "ÇIKTI (sadece bu JSON, başka metin yazma)",
        "critical": "KRİTİK",
    },
    "en": {
        "channel_id": "CHANNEL IDENTITY",
        "topic": "Topic",
        "language": "English",
        "task": "TASK",
        "forbidden_intro": "DO NOT produce anything similar to these (paraphrase included):",
        "forbidden_end": "─── end of list ───",
        "topic_rotation": "TOPIC ROTATION (last 7 days)",
        "output_intro": "OUTPUT (only this JSON, no other text)",
        "critical": "CRITICAL",
    },
    "de": {
        "channel_id": "KANAL-IDENTITÄT",
        "topic": "Thema",
        "language": "Deutsch",
        "task": "AUFGABE",
        "forbidden_intro": "ERZEUGE NIEMALS etwas Ähnliches (Paraphrasen eingeschlossen):",
        "forbidden_end": "─── Ende der Liste ───",
        "topic_rotation": "THEMENROTATION (letzte 7 Tage)",
        "output_intro": "AUSGABE (nur dieses JSON, keinen anderen Text)",
        "critical": "WICHTIG",
    },
    "es": {
        "channel_id": "IDENTIDAD DEL CANAL",
        "topic": "Tema",
        "language": "Español",
        "task": "TAREA",
        "forbidden_intro": "NO produzcas nada similar a estos textos (paráfrasis incluida):",
        "forbidden_end": "─── fin de la lista ───",
        "topic_rotation": "ROTACIÓN DE TEMAS (últimos 7 días)",
        "output_intro": "SALIDA (solo este JSON, sin otro texto)",
        "critical": "CRÍTICO",
    },
    "fr": {
        "channel_id": "IDENTITÉ DE LA CHAÎNE",
        "topic": "Sujet",
        "language": "Français",
        "task": "TÂCHE",
        "forbidden_intro": "NE PRODUIS RIEN de similaire à ces textes (paraphrase incluse) :",
        "forbidden_end": "─── fin de la liste ───",
        "topic_rotation": "ROTATION DES SUJETS (7 derniers jours)",
        "output_intro": "SORTIE (uniquement ce JSON, aucun autre texte)",
        "critical": "CRITIQUE",
    },
}


def get_phrases(language: str) -> dict[str, str]:
    """Return the localized phrase dict, falling back to Turkish for unknown codes."""
    return GENERATOR_PHRASES.get(language, GENERATOR_PHRASES["tr"])
