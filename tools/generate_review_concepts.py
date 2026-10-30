"""Generate ten comparable vector mockups, independent of the production QML UI."""

import textwrap
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "docs/ux/concepts"
ROWS = [
    (
        "00:00",
        "00:18",
        "Maria",
        "Apriamo la riunione con il calendario delle attività del prossimo mese.",
    ),
    (
        "00:18",
        "00:42",
        "Luca",
        "Propongo di confermare il laboratorio del venerdì e aggiornare le famiglie entro lunedì.",
    ),
    (
        "00:42",
        "00:58",
        "Anna",
        "Per il laboratorio servono due gruppi. Posso coordinare il primo e preparare i materiali.",
    ),
    (
        "00:50",
        "01:03",
        "Luca",
        "Sono disponibile per il secondo gruppo. Verifichiamo insieme gli orari.",
    ),
    (
        "00:58",
        "01:20",
        "Maria",
        "Bene, registriamo le disponibilità e fissiamo la verifica per martedì.",
    ),
    (
        "01:20",
        "01:45",
        "Paolo",
        "Invierò il riepilogo delle decisioni e raccoglierò le conferme.",
    ),
]
NAMES = [
    "Lista compatta",
    "Editor a due colonne",
    "Documento continuo",
    "Timeline degli speaker",
    "Revisione guidata",
]


def concept(number, follow):
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1650" height="930" viewBox="0 0 1650 930">',
        '<defs><filter id="raised" x="-20%" y="-30%" width="140%" height="160%"><feDropShadow dx="5" dy="5" stdDeviation="6" flood-color="#050505"/><feDropShadow dx="-2" dy="-2" stdDeviation="3" flood-color="#303030" flood-opacity=".65"/></filter></defs>',
    ]

    def rect(x, y, w, h, fill="#191919", stroke="none", r=12):
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}"/>'
        )

    def txt(x, y, value, size=16, color="#e1e1e1", weight=400):
        parts.append(
            f'<text x="{x}" y="{y}" font-family="DejaVu Sans,sans-serif" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>'
        )

    def button(x, y, w, label, selected=False):
        rect(x, y, w, 34, "#202020", "#ff6600" if selected else "#353535", 9)
        txt(x + 12, y + 23, label, 13, "#ff6600" if selected else "#e1e1e1")

    def textlines(x, y, value, width=95):
        for line in textwrap.wrap(value, width):
            txt(x, y, line, 17)
            y += 27

    rect(0, 0, 1650, 930, "#141414", r=0)
    rect(18, 18, 195, 894, "#191919")
    txt(34, 59, "UltraTranscribr", 19, weight=600)
    txt(34, 84, "5.5 · Proposta di revisione", 12, "#aaaaaa")
    for i, label in enumerate(
        ["Live", "File", "Riunione", "Cronologia", "Impostazioni", "Log"]
    ):
        if i == 2:
            rect(30, 112 + i * 54, 170, 42, "#252525", "#ff6600")
        txt(45, 140 + i * 54, label, 16, "#ff6600" if i == 2 else "#cccccc")
    txt(34, 868, "Dati dimostrativi", 12, "#aaaaaa")
    txt(241, 51, "Riunione di prova · 29/10/2026 19:14", 22, weight=500)
    txt(
        241,
        80,
        ("B" if follow else "A") + str(number) + " · " + NAMES[number - 1],
        14,
        "#aaaaaa",
    )
    txt(1310, 51, "Tutte le modifiche salvate", 14, "#cccccc")
    rect(238, 103, 1385, 70, "#202020")
    button(252, 121, 75, "Ⅱ" if follow else "▶")
    txt(345, 144, ("00:52" if follow else "00:00") + " / 01:45", 16)
    rect(505, 135, 680, 5, "#484848", r=2)
    if follow:
        rect(505, 135, 337, 5, "#ff6600", r=2)
    button(1210, 121, 185, "Segui audio ✓" if follow else "Audio originale", follow)
    button(1407, 121, 196, "Pausa sincronizzazione" if follow else "Velocità 1×")
    rect(238, 189, 260, 716, "#191919")
    txt(254, 219, "Interlocutori (9)", 17, weight=500)
    for i, name in enumerate(
        ["Maria", "Luca", "Anna", "Paolo", "Elena", "Sara", "Marco", "Giulia", "Andrea"]
    ):
        txt(254, 259 + i * 47, str(i + 1), 13, "#aaaaaa")
        button(280, 238 + i * 47, 192, name + "  ✎")
    rect(485, 238, 5, 437, "#505050", r=2)
    rect(485, 238, 5, 260, "#aaaaaa", r=2)
    button(254, 755, 225, "Esporta TXT")
    button(254, 801, 225, "Esporta SRT")
    txt(520, 219, "Interventi", 20, weight=500)
    button(1340, 193, 115, "↶ Annulla")
    button(1470, 193, 135, "↷ Ripristina")
    x, y, w = 520, 239, 1082
    if number == 1:
        for i, (start, end, name, text) in enumerate(ROWS):
            yy = y + i * 101
            active = follow and i in (2, 3)
            rect(
                x,
                yy,
                w,
                91,
                "#25201c" if active else "#1b1b1b",
                "#ff6600" if active else "#303030",
            )
            button(x + 12, yy + 12, 82, start, active)
            button(x + 108, yy + 12, 130, name + " ⌄")
            textlines(x + 255, yy + 32, text, 76)
            if i == 3:
                txt(x + 255, yy + 75, "Voci sovrapposte · 00:50–00:58", 12, "#ff8844")
    elif number == 2:
        rect(x, y, 300, 640, "#1b1b1b")
        for i, (start, end, name, text) in enumerate(ROWS):
            yy = y + 8 + i * 98
            active = i == 2
            rect(
                x + 8,
                yy,
                284,
                90,
                "#2b231d" if active else "#202020",
                "#ff6600" if active else "#303030",
            )
            txt(x + 20, yy + 27, start + "  " + name, 15)
            textlines(x + 20, yy + 54, text[:54] + "…", 28)
        rect(x + 316, y, w - 316, 640, "#1b1b1b")
        txt(x + 340, y + 38, "00:42–00:58 · Anna", 19)
        button(x + 340, y + 62, 190, "Interlocutore · Anna ⌄")
        textlines(x + 340, y + 136, ROWS[2][3], 57)
        txt(x + 340, y + 270, "Voci sovrapposte: Luca · 00:50–00:58", 14, "#ff8844")
        txt(x + 340, y + 589, "Modifica salvata · Ctrl+Z per annullare", 13, "#aaaaaa")
    elif number == 3:
        rect(x, y, w, 640, "#1b1b1b")
        for i, (start, end, name, text) in enumerate(ROWS):
            yy = y + 12 + i * 101
            active = follow and i in (2, 3)
            if active:
                rect(x + 12, yy, w - 35, 94, "#2b231d", "#ff6600")
            button(x + 23, yy + 9, 78, start, active)
            button(x + 116, yy + 9, 130, name + " ⌄")
            textlines(x + 23, yy + 68, text, 104)
    elif number == 4:
        rect(x, y, w, 230, "#1b1b1b")
        for i, name in enumerate(["Maria", "Luca", "Anna", "Paolo"]):
            txt(x + 14, y + 55 + i * 44, name, 14)
        for i, (start, end, name, text) in enumerate(ROWS):
            lane = ["Maria", "Luca", "Anna", "Paolo"].index(name)

            def seconds(v):
                a, b = v.split(":")
                return int(a) * 60 + int(b)

            xx = x + 110 + seconds(start) / 105 * 940
            ww = (seconds(end) - seconds(start)) / 105 * 940
            rect(
                xx,
                y + 32 + lane * 44,
                ww,
                30,
                "#4c2c17" if follow and i in (2, 3) else "#3a3a3a",
                "#ff6600" if follow and i in (2, 3) else "#666666",
                5,
            )
            txt(xx + 7, y + 53 + lane * 44, start, 12)
        if follow:
            xx = x + 110 + 52 / 105 * 940
            rect(xx, y + 15, 2, 198, "#ff6600", r=0)
        for i in range(3):
            start, end, name, text = ROWS[i + 2]
            yy = y + 248 + i * 116
            rect(x, yy, w, 106, "#24201c" if follow and i < 2 else "#1b1b1b")
            button(x + 14, yy + 10, 90, start)
            button(x + 120, yy + 10, 130, name + " ⌄")
            textlines(x + 15, yy + 73, text, 102)
    else:
        for i, (rowidx, yy, hh) in enumerate(
            [(1, y, 115), (2, y + 132, 337), (3, y + 486, 140)]
        ):
            start, end, name, text = ROWS[rowidx]
            active = i == 1
            rect(
                x,
                yy,
                w,
                hh,
                "#25201c" if follow and active else "#1b1b1b",
                "#ff6600" if active else "#363636",
            )
            txt(
                x + 18,
                yy + 30,
                [
                    "Précédent".replace("Précédent", "Precedente"),
                    "Intervento corrente",
                    "Successivo",
                ][i],
                14,
                "#aaaaaa",
            )
            button(x + 18, yy + 45, 86, start, follow and active)
            button(x + 120, yy + 45, 130, name + " ⌄")
            textlines(x + 18, yy + 115 if active else yy + 101, text, 100)
            if active:
                txt(
                    x + 18,
                    yy + 200,
                    "Voci sovrapposte con Luca · 00:50–00:58",
                    14,
                    "#ff8844",
                )
                button(x + 18, yy + 273, 150, "← Precedente")
                button(x + 185, yy + 273, 150, "Successivo →")
    rect(1613, 239, 6, 640, "#404040", r=3)
    rect(1613, 239, 6, 290, "#aaaaaa", r=3)
    if follow:
        txt(
            520,
            907,
            "00:52 · Anna e Luca attivi · clic sui timestamp per cercare · follow sospeso durante la correzione",
            13,
            "#cccccc",
        )
    parts.append("</svg>")
    return "\n".join(parts)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    for follow in (False, True):
        for n in range(1, 6):
            (ROOT / f"{'B' if follow else 'A'}{n}.svg").write_text(concept(n, follow))
    options = "".join(
        f'<option value="{n}">{name}</option>' for n, name in enumerate(NAMES, 1)
    )
    page = (
        """<!doctype html><html lang="it"><meta charset="utf-8"><title>UltraTranscribr · 10 proposte editor</title>
<style>body{margin:0;background:#141414;color:#e1e1e1;font:16px system-ui}header{display:flex;gap:18px;align-items:center;padding:16px;position:sticky;top:0;background:#141414}select,a{color:#e1e1e1;background:#252525;padding:10px;border:1px solid #555;border-radius:8px}img{width:100%;display:block}section{max-width:1650px;margin:auto}a{margin-left:auto}</style>
<header><strong>Revisione · confronto delle dieci proposte</strong><select id="variant" aria-label="Layout">"""
        + options
        + """</select><select id="follow" aria-label="Sincronizzazione"><option value="A">Solo UI</option><option value="B">Con follow audio</option></select><a id="full" href="A1.svg">Apri immagine</a></header><section><img id="preview" src="A1.svg" alt="Proposta di revisione UltraTranscribr"></section><script>
const variant=document.getElementById('variant'), follow=document.getElementById('follow');
function show(){const path=follow.value+variant.value+'.svg';document.getElementById('preview').src=path;document.getElementById('full').href=path;}
variant.onchange=show;follow.onchange=show;</script></html>"""
    )
    (ROOT / "index.html").write_text(page)


if __name__ == "__main__":
    main()
