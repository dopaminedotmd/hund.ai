"""Single source of truth for response formatting directives and presentation constraints."""
from __future__ import annotations

from typing import Sequence
from .task_brief import ResponseFormat, TaskBrief


def get_response_policy_rules(*, language: str = "sv") -> list[str]:
    """Return canonical response formatting and presentation rules for system prompt assembly."""
    is_sv = language.lower().startswith("sv")

    if is_sv:
        return [
            "Standardformatet är naturlig, kompakt prosa i 1-4 rader. Gör inte varje svar till en rapport.",
            "Välj struktur i denna ordning: vanlig prosa först; korta stycken när ett ämne skiftar; lista först när relationerna verkligen behöver räknas eller jämföras.",
            "Använd punktlistor endast när innehållet faktiskt består av minst tre jämförbara saker, tydliga steg eller alternativ som blir lättare att skanna.",
            "Formatering är en förmåga, inte en husstil: använd rubriker, tabeller, fetstil och listor sparsamt och bara när strukturen tillför information.",
            "När en lista passar: håll den kort, konsekvent och luftig. När en lista inte behövs: skriv som hund i vanlig prosa.",
            "Fetstil är semantisk betoning, inte dekoration. Undvik ett fetstilt label-prefix på varje listpunkt och undvik rubriker i svar som redan är korta.",
            "Använd backticks (`kod`) för filnamn, kommandon, funktioner och tekniska termer.",
            "När kodsnuttar presenteras: introducera koden kort med 1 mening som förklarar varför den behövs och hur den används innan kodblocket visas.",
            "När verktyg (som write_file eller edit_file) skapar eller ändrar filer renderas koden och diffen automatiskt i aktivitetsfeeden. Hund behöver därför INTE upprepa hela källkoden i sin svarsbox, utan håller sitt svar rent, precist och i tredje person.",
            "Deklarera osäkerhet ärligt: om benchmark eller data är uppskattad eller saknas, märk den tydligt som en uppskattning.",
            "När användaren beskriver hur hen skriver eller vill att något ska se ut är det en spec att agera på och genomföra (uppdatera mallen, koden eller skillen), inte fakta att bekräfta eller fråga om lov för.",
        ]

    return [
        "The standard response format is natural, concise prose in 1-4 lines. Do not turn every answer into a report.",
        "Choose structure in order: plain prose first; short paragraphs when a topic shifts; lists only when items genuinely need counting or step-by-step scanning.",
        "Use bullet lists only when content consists of at least three comparable items, sequential steps, or options that benefit from scanning.",
        "Formatting is an ability, not a house style: use headings, tables, bold text, and lists sparingly and only when structure adds clarity.",
        "When a list fits: keep it short and consistent. When a list is not needed: write in regular prose.",
        "Bold is for semantic emphasis, not decoration. Avoid bold label prefixes on every list bullet and avoid headings in short answers.",
        "Use backticks (`code`) for filenames, commands, functions, and technical identifiers.",
        "When presenting code blocks: introduce the snippet with 1 sentence explaining its purpose and usage before showing it.",
        "When tools (like write_file or edit_file) create or modify files, code and diffs render automatically in the activity feed. Do not duplicate whole file content in the assistant response box.",
        "State uncertainty honestly: label benchmarks, estimates, or unverified claims explicitly as estimates.",
        "When the user describes how they write or want something to look, treat it as a specification to execute immediately (updating the template, code, or skill), not as idle facts to confirm or ask permission about.",
    ]


def render_advisory_directives(brief: TaskBrief, *, language: str = "sv") -> str:
    """Format turn-local advisory response directives based on TaskBrief."""
    is_sv = language.lower().startswith("sv")
    directives: list[str] = []

    if brief.preferred_format == ResponseFormat.PROSE:
        directives.append("Formatera som kompakt prosa (1-4 rader)." if is_sv else "Format as compact prose (1-4 lines).")
    elif brief.preferred_format == ResponseFormat.LIST:
        directives.append("Presentera som en kort, fokuserad lista." if is_sv else "Present as a short, focused list.")
    elif brief.preferred_format == ResponseFormat.TABLE:
        directives.append("Presentera som en jämförande tabell." if is_sv else "Present as a comparative table.")
    elif brief.preferred_format == ResponseFormat.CODE or brief.show_code:
        directives.append("Introducera koden med 1 förklarande mening." if is_sv else "Introduce code snippet with 1 explanatory sentence.")

    if brief.requires_disk_vram_separation:
        directives.append(
            "Separera tydligt system-RAM, GPU-VRAM och diskutrymme i rekommendationen."
            if is_sv
            else "Strictly separate system RAM, GPU VRAM, and disk storage in recommendations."
        )

    if brief.requires_uncertainty_disclosure:
        directives.append(
            "Märk uppskattningar och overifierade antaganden tydligt."
            if is_sv
            else "Clearly disclose estimates and unverified assumptions."
        )

    if brief.task_type.value == "self_knowledge" and (brief.relevant_command or "").startswith("skill"):
        directives.append(
            "Ge en kort pedagogisk förklaring av vad en skill är i användartermer (återanvändbart sätt att utföra en uppgift: när den används, steg och verifiering) utan intern teknisk jargong eller scheman. Använd inga verktyg."
            if is_sv
            else "Provide a concise, pedagogical explanation of what a skill is in plain user terms (a reusable way to perform a task: when to use, steps, verification) without technical jargon. Use zero tools."
        )

    if not directives:
        return ""

    header = "[RÅDGIVANDE SVARSDIREKTIV]" if is_sv else "[ADVISORY RESPONSE DIRECTIVES]"
    return header + "\n" + "\n".join(f"• {d}" for d in directives)
