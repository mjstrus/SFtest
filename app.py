"""
Walidator e-Sprawozdań Finansowych
Streamlit UI
"""

import streamlit as st
from validator.core import WalidatorESprawozdan, WynikWalidacji, Blad

# ---------------------------------------------------------------------------
# Konfiguracja strony
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Walidator e-Sprawozdań",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    .stApp { font-family: 'Inter', 'Segoe UI', sans-serif; }
    .header-box {
        background: linear-gradient(135deg, #0d1b2a 0%, #1b2d45 100%);
        color: white; padding: 2rem 2.5rem; border-radius: 12px; margin-bottom: 2rem;
    }
    .header-box h1 { font-size: 1.8rem; margin: 0; font-weight: 700; }
    .header-box p  { margin: 0.5rem 0 0 0; opacity: 0.8; font-size: 0.95rem; }

    .status-green  { background:#d1fae5; border-left:5px solid #10b981; padding:1.2rem 1.5rem; border-radius:8px; margin:1rem 0; }
    .status-red    { background:#fee2e2; border-left:5px solid #ef4444; padding:1.2rem 1.5rem; border-radius:8px; margin:1rem 0; }
    .status-yellow { background:#fef3c7; border-left:5px solid #f59e0b; padding:1.2rem 1.5rem; border-radius:8px; margin:1rem 0; }
    .status-green h3  { color:#065f46; margin:0 0 0.3rem 0; }
    .status-red h3    { color:#7f1d1d; margin:0 0 0.3rem 0; }
    .status-yellow h3 { color:#78350f; margin:0 0 0.3rem 0; }
    .status-green p, .status-red p, .status-yellow p { margin:0; font-size:0.92rem; }

    .info-grid { display:grid; grid-template-columns:1fr 1fr 1fr; gap:1rem; margin:1.5rem 0; }
    .info-card { background:white; border-radius:8px; padding:1rem 1.2rem; border:1px solid #e5e7eb; }
    .info-card .label { font-size:0.75rem; color:#6b7280; text-transform:uppercase; letter-spacing:0.05em; }
    .info-card .value { font-size:1rem; font-weight:600; color:#111827; margin-top:0.2rem; }

    .blad-krytyczny  { background:#fff1f2; border:1px solid #fecdd3; border-left:4px solid #ef4444; border-radius:6px; padding:0.9rem 1.1rem; margin:0.5rem 0; }
    .blad-ostrzezenie{ background:#fffbeb; border:1px solid #fde68a;  border-left:4px solid #f59e0b; border-radius:6px; padding:0.9rem 1.1rem; margin:0.5rem 0; }
    .blad-krytyczny .badge  { background:#ef4444; color:white; font-size:0.7rem; padding:0.15rem 0.5rem; border-radius:4px; font-weight:700; }
    .blad-ostrzezenie .badge{ background:#f59e0b; color:white; font-size:0.7rem; padding:0.15rem 0.5rem; border-radius:4px; font-weight:700; }
    .blad-kat    { font-size:0.78rem; color:#6b7280; margin-left:0.5rem; }
    .blad-opis   { font-weight:600; color:#111827; margin:0.3rem 0 0 0; font-size:0.92rem; }
    .blad-szczegoly { color:#6b7280; font-size:0.85rem; margin:0.2rem 0 0 0; }

    .stat-pill   { display:inline-block; padding:0.3rem 0.8rem; border-radius:20px; font-size:0.82rem; font-weight:600; margin:0.2rem; }
    .pill-red    { background:#fee2e2; color:#b91c1c; }
    .pill-yellow { background:#fef3c7; color:#92400e; }
    .pill-green  { background:#d1fae5; color:#065f46; }
    .divider     { border:none; border-top:1px solid #e5e7eb; margin:1.5rem 0; }
    .raport-txt  { background:#1e293b; color:#e2e8f0; font-family:'Courier New',monospace; font-size:0.85rem;
                   padding:1.5rem; border-radius:8px; white-space:pre-wrap; word-break:break-word; max-height:400px; overflow-y:auto; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Pomocnicza: generowanie raportu tekstowego
# ---------------------------------------------------------------------------

def generuj_raport(wynik: WynikWalidacji) -> str:
    linie = []
    linie.append("=" * 70)
    linie.append("RAPORT WALIDACJI e-SPRAWOZDANIA FINANSOWEGO")
    linie.append("=" * 70)
    linie.append(f"Podmiot:            {wynik.podmiot_nazwa or 'BRAK'}")
    linie.append(f"NIP:                {wynik.podmiot_nip or 'BRAK'}")
    linie.append(f"Typ jednostki:      {wynik.typ_jednostki or 'NIEZNANY'}")
    linie.append(f"Okres:              {wynik.okres_od} — {wynik.okres_do}")
    linie.append(f"Data sporządzenia:  {wynik.data_sporzadzenia or 'BRAK'}")
    linie.append("-" * 70)

    krity   = [b for b in wynik.bledy if b.poziom == "KRYTYCZNY"]
    ostrzeż = [b for b in wynik.bledy if b.poziom == "OSTRZEŻENIE"]

    if wynik.status == "ZIELONE":
        linie.append("[ZIELONE ŚWIATŁO] Plik jest poprawny. Można wysłać do KRS/KAS.")
    elif wynik.status == "ŻÓŁTE":
        linie.append(f"[ŻÓŁTE ŚWIATŁO] Wykryto {len(ostrzeż)} ostrzeżeń. Zalecana weryfikacja.")
    else:
        linie.append(f"[CZERWONE ŚWIATŁO] Wykryto {len(krity)} błędów krytycznych.")

    if krity:
        linie.append("\nBŁĘDY KRYTYCZNE:")
        for i, b in enumerate(krity, 1):
            linie.append(f"  {i}. [{b.kategoria}] {b.opis}")
            if b.szczegoly:
                linie.append(f"     → {b.szczegoly}")

    if ostrzeż:
        linie.append("\nOSTRZEŻENIA:")
        for i, b in enumerate(ostrzeż, 1):
            linie.append(f"  {i}. [{b.kategoria}] {b.opis}")
            if b.szczegoly:
                linie.append(f"     → {b.szczegoly}")

    linie.append("=" * 70)
    return "\n".join(linie)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.markdown("""
<div class="header-box">
    <h1>📋 Walidator e-Sprawozdań Finansowych</h1>
    <p>Głęboka walidacja logiczna, merytoryczna i kompletności danych XML &mdash; jednostki mikro, małe i inne (pełne)</p>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns([2, 1])

with col1:
    plik = st.file_uploader(
        "Wgraj plik e-Sprawozdania (XML)",
        type=["xml"],
        help="Obsługiwane struktury: JednostkaMikro, JednostkaMala, JednostkaInna (format MF)"
    )

with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    st.info(
        "**Co sprawdza walidator:**\n"
        "- Logika dat (rok obrotowy vs data sporządzenia)\n"
        "- NIP / REGON / KRS (sumy kontrolne)\n"
        "- Kompletność sekcji (Bilans, RZiS, itd.)\n"
        "- Aktywa = Pasywa\n"
        "- RZiS ↔ Bilans (wynik netto)"
    )

if plik is not None:
    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    try:
        xml_bytes = plik.read()
        try:
            xml_tekst = xml_bytes.decode("utf-8")
        except UnicodeDecodeError:
            xml_tekst = xml_bytes.decode("windows-1250", errors="replace")

        walidator = WalidatorESprawozdan()
        wynik = walidator.waliduj(xml_tekst)

        krity   = [b for b in wynik.bledy if b.poziom == "KRYTYCZNY"]
        ostrzeż = [b for b in wynik.bledy if b.poziom == "OSTRZEŻENIE"]

        # Status banner
        if wynik.status == "ZIELONE":
            st.markdown("""
            <div class="status-green">
                <h3>✅ ZIELONE ŚWIATŁO — Plik jest poprawny</h3>
                <p>Nie wykryto błędów krytycznych ani ostrzeżeń. Plik można wysłać do KRS/KAS.</p>
            </div>""", unsafe_allow_html=True)
        elif wynik.status == "ŻÓŁTE":
            st.markdown(f"""
            <div class="status-yellow">
                <h3>⚠️ ŻÓŁTE ŚWIATŁO — Wykryto ostrzeżenia</h3>
                <p>Brak błędów krytycznych, ale znaleziono {len(ostrzeż)} ostrzeżeń. Zalecana weryfikacja przed wysłaniem.</p>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="status-red">
                <h3>🔴 CZERWONE ŚWIATŁO — Wykryto błędy krytyczne</h3>
                <p>Znaleziono {len(krity)} błędów krytycznych i {len(ostrzeż)} ostrzeżeń. Plik zostanie odrzucony przez KRS/KAS.</p>
            </div>""", unsafe_allow_html=True)

        # Info o podmiocie
        st.markdown(f"""
        <div class="info-grid">
            <div class="info-card"><div class="label">Podmiot</div><div class="value">{wynik.podmiot_nazwa or '—'}</div></div>
            <div class="info-card"><div class="label">NIP</div><div class="value">{wynik.podmiot_nip or '—'}</div></div>
            <div class="info-card"><div class="label">Typ jednostki</div><div class="value">{wynik.typ_jednostki or '—'}</div></div>
            <div class="info-card"><div class="label">Okres od</div><div class="value">{wynik.okres_od or '—'}</div></div>
            <div class="info-card"><div class="label">Okres do</div><div class="value">{wynik.okres_do or '—'}</div></div>
            <div class="info-card"><div class="label">Data sporządzenia</div><div class="value">{wynik.data_sporzadzenia or '—'}</div></div>
        </div>""", unsafe_allow_html=True)

        # Liczniki
        if wynik.bledy:
            st.markdown(
                f'<span class="stat-pill pill-red">🔴 Krytyczne: {len(krity)}</span>'
                f'<span class="stat-pill pill-yellow">⚠️ Ostrzeżenia: {len(ostrzeż)}</span>',
                unsafe_allow_html=True
            )
            st.markdown("<br>", unsafe_allow_html=True)

        # Błędy krytyczne
        if krity:
            st.subheader("🔴 Błędy krytyczne")
            for i, b in enumerate(krity, 1):
                szcz = f"<p class='blad-szczegoly'>{b.szczegoly}</p>" if b.szczegoly else ""
                st.markdown(f"""
                <div class="blad-krytyczny">
                    <span class="badge">KRYTYCZNY</span><span class="blad-kat">{b.kategoria}</span>
                    <p class="blad-opis">{i}. {b.opis}</p>{szcz}
                </div>""", unsafe_allow_html=True)

        # Ostrzeżenia
        if ostrzeż:
            st.subheader("⚠️ Ostrzeżenia")
            for i, b in enumerate(ostrzeż, 1):
                szcz = f"<p class='blad-szczegoly'>{b.szczegoly}</p>" if b.szczegoly else ""
                st.markdown(f"""
                <div class="blad-ostrzezenie">
                    <span class="badge">OSTRZEŻENIE</span><span class="blad-kat">{b.kategoria}</span>
                    <p class="blad-opis">{i}. {b.opis}</p>{szcz}
                </div>""", unsafe_allow_html=True)

        if not wynik.bledy:
            st.success("Brak jakichkolwiek błędów i ostrzeżeń.")

        # Eksport
        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        st.subheader("📄 Eksport raportu tekstowego")
        raport = generuj_raport(wynik)
        st.markdown(f'<div class="raport-txt">{raport}</div>', unsafe_allow_html=True)
        st.download_button(
            label="⬇️ Pobierz raport .txt",
            data=raport.encode("utf-8"),
            file_name=f"walidacja_{wynik.podmiot_nip or 'brak_nip'}.txt",
            mime="text/plain",
        )

    except Exception as e:
        st.error(f"Nieoczekiwany błąd podczas walidacji: {e}")
        st.exception(e)

else:
    st.markdown("""
    <div style="background:white; border:2px dashed #d1d5db; border-radius:12px;
                padding:3rem; text-align:center; margin:1rem 0;">
        <p style="font-size:2.5rem; margin:0;">📁</p>
        <p style="font-weight:600; color:#374151; margin:0.5rem 0;">Przeciągnij i upuść plik XML lub kliknij przycisk powyżej</p>
        <p style="color:#9ca3af; font-size:0.88rem; margin:0;">Format: e-Sprawozdanie MF (JPK_SF) — jednostki mikro, małe, inne</p>
    </div>
    """, unsafe_allow_html=True)
