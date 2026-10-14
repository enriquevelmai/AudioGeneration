"""Tests del parser de guiones."""

from __future__ import annotations

import pytest

from podcast_tts.script_parser import (
    Music,
    ParsedScript,
    Pause,
    ScriptParseError,
    Sfx,
    Speech,
    chunk_text,
    parse_file,
    parse_script,
    split_sentences,
)


def speeches(script: ParsedScript) -> list[Speech]:
    return [s for s in script.segments if isinstance(s, Speech)]


def test_inline_tags_from_decisions_example() -> None:
    script = parse_script(
        "[voz:ana] Hola. [pausa:1.5] [voz:carlos lang=en] Hi. [musica:intro.mp3 vol=0.3]"
    )
    assert script.segments == [
        Speech(voice="ana", text="Hola.", line=1),
        Pause(seconds=1.5, line=1),
        Speech(voice="carlos", text="Hi.", lang="en", line=1),
        Music(path="intro.mp3", volume=0.3, fade=0.0, line=1),
    ]


def test_voice_attributes_persist_until_next_voice() -> None:
    script = parse_script(
        "[voice:ana lang=en speed=0.95 engine=xtts]\nFirst line.\nSecond line.\n[voz:carlos]\nHola."
    )
    sp = speeches(script)
    assert [s.voice for s in sp] == ["ana", "carlos"]
    assert sp[0].text == "First line. Second line."
    assert (sp[0].lang, sp[0].speed, sp[0].engine) == ("en", 0.95, "xtts")
    assert (sp[1].lang, sp[1].speed, sp[1].engine) == (None, None, None)


def test_all_tags_and_aliases() -> None:
    text = """[title:Episodio 1]
[voz:ana] Hola.
[pause:2]
[música:fondo.mp3 fondo vol=0.2 fade=3]
[voz:ana] Con música.
[sfx:ding.wav vol=0.8]
[music:stop fade=2]
[musica:outro.mp3 fade=1]
[music:bed.mp3 bg=true]
[titulo:Otro título]
"""
    script = parse_script(text)
    assert script.meta.title == "Otro título"
    segs = script.segments
    assert isinstance(segs[0], Speech)
    assert segs[1] == Pause(seconds=2.0, line=3)
    assert segs[2] == Music(path="fondo.mp3", volume=0.2, fade=3.0, background=True, line=4)
    assert isinstance(segs[3], Speech) and segs[3].text == "Con música."
    assert segs[4] == Sfx(path="ding.wav", volume=0.8, line=6)
    assert segs[5] == Music(path="", fade=2.0, stop=True, line=7)
    assert segs[6] == Music(path="outro.mp3", volume=1.0, fade=1.0, line=8)
    assert segs[7].background is True and segs[7].volume == 0.15


def test_quoted_paths_with_spaces() -> None:
    script = parse_script('[musica:"mi carpeta/intro final.mp3" vol=0.5]')
    assert script.segments[0].path == "mi carpeta/intro final.mp3"


def test_front_matter_and_default_voice() -> None:
    text = """---
title: Mi podcast
lang: es
default_voice: ana
engine: xtts
autor: Enrique
---
Texto sin etiqueta de voz.
"""
    script = parse_script(text)
    assert script.meta.title == "Mi podcast"
    assert script.meta.lang == "es"
    assert script.meta.default_voice == "ana"
    assert script.meta.default_engine == "xtts"
    assert script.meta.extra == {"autor": "Enrique"}
    sp = speeches(script)
    assert sp[0].voice == "ana" and sp[0].line == 8


def test_front_matter_fallback_without_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("sin yaml")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    script = parse_script('---\ntitle: "Hola: mundo"\nparagraph_pause: 0.8\n---\n[voz:a] Uno.\n\nDos.')
    assert script.meta.title == "Hola: mundo"
    assert script.meta.paragraph_pause == 0.8
    assert Pause(seconds=0.8, line=7) in script.segments


def test_unclosed_front_matter() -> None:
    with pytest.raises(ScriptParseError, match="Línea 1"):
        parse_script("---\ntitle: x\n[voz:a] hola")


def test_comments_and_headings_ignored() -> None:
    script = parse_script("# Encabezado\n[voz:ana] Hola.\n## [musica:x.mp3]\n<!-- nota -->\nAdiós.")
    assert [type(s) for s in script.segments] == [Speech]
    assert script.segments[0].text == "Hola. Adiós."


def test_paragraph_pause_default_and_override() -> None:
    text = "[voz:ana] Uno.\n\nDos.\n\n\n[pausa:1] Tres."
    script = parse_script(text)
    assert [type(s).__name__ for s in script.segments] == ["Speech", "Pause", "Speech", "Pause", "Speech"]
    assert script.segments[1].seconds == 0.4
    assert script.segments[3].seconds == 1.0  # la pausa explícita no se duplica
    script2 = parse_script(text, paragraph_pause=0)
    assert [type(s).__name__ for s in script2.segments] == ["Speech", "Speech", "Pause", "Speech"]


def test_split_sentences() -> None:
    assert split_sentences("Hola. ¿Qué tal? ¡Bien!\nOtra línea… Fin") == [
        "Hola.", "¿Qué tal?", "¡Bien!", "Otra línea…", "Fin",
    ]
    assert split_sentences('Dijo "vale." Y se fue.') == ['Dijo "vale."', "Y se fue."]


def test_chunking_respects_max_chars_and_sentences() -> None:
    sentences = [f"Esta es la frase número {i} del texto de prueba." for i in range(20)]
    text = " ".join(sentences)
    chunks = chunk_text(text, max_chars=120)
    assert all(len(c) <= 120 for c in chunks)
    assert " ".join(chunks) == text
    for c in chunks:  # cada trozo empieza y acaba en frase completa
        assert c.startswith("Esta") and c.endswith(".")


def test_chunking_long_sentence_split_at_commas_or_words() -> None:
    long = ", ".join(["un trozo de texto bastante largo"] * 20) + "."
    chunks = chunk_text(long, max_chars=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    assert " ".join(chunks) == long
    words = chunk_text("palabra " * 100, max_chars=50)
    assert all(len(c) <= 50 for c in words)


def test_parser_produces_multiple_speech_chunks() -> None:
    text = "[voz:ana] " + " ".join(f"Frase {i} con algo de texto." for i in range(30))
    script = parse_script(text, max_chars=80)
    sp = speeches(script)
    assert len(sp) > 3 and all(len(s.text) <= 80 and s.voice == "ana" for s in sp)


@pytest.mark.parametrize(
    "text, line, fragment",
    [
        ("[voz:ana] hola\n[foo:bar]", 2, "etiqueta desconocida"),
        ("[voz:ana] hola\n\n[vos:carlos] x", 3, "etiqueta desconocida"),
        ("[pausa:abc]", 1, "número"),
        ("[pausa:-1]", 1, ">="),
        ("[musica:a.mp3 vol=2]", 1, "<="),
        ("[voz:ana engine=otro]", 1, "motor desconocido"),
        ("[voz:ana color=rojo]", 1, "desconocido"),
        ("[sfx:a.wav fondo]", 1, "desconocido"),
        ("\n\nTexto sin voz", 3, "sin voz"),
        ("[voz:]", 1, "necesita un valor"),
    ],
)
def test_errors_include_line_number(text: str, line: int, fragment: str) -> None:
    with pytest.raises(ScriptParseError) as exc:
        parse_script(text)
    assert exc.value.line == line
    assert f"Línea {line}" in str(exc.value)
    assert fragment in str(exc.value)


def test_json_roundtrip(tmp_path) -> None:
    text = "---\ntitle: T\nextra_key: 1\n---\n[voz:ana lang=en] Hi. [pausa:1] [sfx:a.wav] [musica:b.mp3 fondo]\n[musica:stop]"
    script = parse_script(text)
    data = script.to_json()
    again = ParsedScript.from_json(data)
    assert again == script
    assert '"type": "speech"' in data
    path = tmp_path / "g.md"
    path.write_text(text, encoding="utf-8")
    assert parse_file(path) == script
    assert script.voices == ["ana"]


def test_crlf_and_bom() -> None:
    script = parse_script("﻿---\r\ntitle: X\r\n---\r\n[voz:ana] Hola.\r\n")
    assert script.meta.title == "X"
    assert speeches(script)[0].text == "Hola."


# --------------------------------------------------------------------------- #
# Regresiones de la revisión de código
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "[pausa:nan]",
        "[pausa:inf]",
        "[pausa:1e308]",
        "[pausa:601]",
        "[musica:a.mp3 fondo fade=inf]",
        "[musica:a.mp3 fade=1e9]",
        "[musica:stop fade=nan]",
        "[sfx:a.wav vol=nan]",
        "[voz:ana speed=nan] hola",
    ],
)
def test_non_finite_or_huge_numbers_rejected(text: str) -> None:
    with pytest.raises(ScriptParseError) as exc:
        parse_script(text)
    assert exc.value.line == 1


def test_paragraph_pause_front_matter_bounded() -> None:
    with pytest.raises(ScriptParseError):
        parse_script("---\nparagraph_pause: .inf\n---\n[voz:ana] hola")
    with pytest.raises(ScriptParseError):
        parse_script("---\nparagraph_pause: 1000\n---\n[voz:ana] hola")


def test_multiline_html_comment_not_synthesized() -> None:
    text = (
        "[voz:ana] Hola.\n"
        "<!-- nota interna\n"
        "que ocupa varias líneas\n"
        "-->\n"
        "Adiós. <!-- en línea --> Fin.\n"
        "Texto <!-- empieza\n"
        "sigue --> resto.\n"
        "[pausa:x]"
    )
    with pytest.raises(ScriptParseError) as exc:
        parse_script(text)
    assert exc.value.line == 8  # la numeración de líneas se conserva
    script = parse_script(text.rsplit("\n", 1)[0])
    joined = " ".join(s.text for s in speeches(script))
    assert "nota" not in joined and "varias" not in joined and "en línea" not in joined
    assert "empieza" not in joined and "sigue" not in joined
    assert "Adiós." in joined and "Fin." in joined and "resto." in joined
    # Un comentario entre dos líneas no corta el párrafo (no añade pausa)
    assert not any(isinstance(s, Pause) for s in script.segments)


def test_unclosed_html_comment_is_error() -> None:
    with pytest.raises(ScriptParseError) as exc:
        parse_script("[voz:ana] Hola.\n\n<!-- sin cerrar\nmás texto")
    assert exc.value.line == 3


@pytest.mark.parametrize("value, expected", [("no", "no"), ("NO", "NO"), ("on", "on"),
                                             ("1.0", "1.0"), ('"no"', "no")])
def test_front_matter_text_fields_stay_text(value: str, expected: str) -> None:
    script = parse_script(f"---\nlang: {value}\ntitle: {value}\nvoz: ana\n---\nHola.")
    assert script.meta.lang == expected
    assert script.meta.title == expected


def test_front_matter_text_fields_without_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "yaml":
            raise ImportError
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    script = parse_script("---\nlang: no\nvoz: ana\n---\nHola.")
    assert script.meta.lang == "no"


def test_markdown_links_and_checkboxes_are_text() -> None:
    script = parse_script(
        "[voz:ana] Mira [la web](https://example.com/a_b) hoy.\n"
        "- [ ] tarea pendiente\n"
        "- [x] tarea hecha [risas] y [10:30]\n"
    )
    joined = " ".join(s.text for s in speeches(script))
    assert "la web hoy." in joined and "https" not in joined
    assert "[ ] tarea pendiente" in joined
    assert "[x] tarea hecha [risas] y [10:30]" in joined


def test_unknown_tag_with_colon_still_errors() -> None:
    with pytest.raises(ScriptParseError) as exc:
        parse_script("[voz:ana] hola\n[desconocida:x]")
    assert exc.value.line == 2
    assert "desconocida" in str(exc.value)
