"""
Walidator e-Sprawozdań Finansowych – single-file Streamlit app
Obsługuje dwa schematy MF:
  - Klasyczny (NIP/REGON/PKD jako nazwy tagów) – starsze wersje
  - JPK_SF v2 (SprFinJednostkaInnaWZlotych, JednostkaMikro itp.) – P_1D=NIP, P_1E=KRS,
    sumy bilansowe jako Aktywa/KwotaA, Informacja dodatkowa jako załącznik PDF, RZiS > L > KwotaA
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional
import re
import streamlit as st


# ============================================================
# Struktury danych
# ============================================================

@dataclass
class Blad:
    poziom: str        # KRYTYCZNY | OSTRZEŻENIE | INFO
    kategoria: str
    opis: str
    szczegoly: str = ""


@dataclass
class WynikWalidacji:
    podmiot_nazwa: str = ""
    podmiot_nip: str = ""
    okres_od: str = ""
    okres_do: str = ""
    data_sporzadzenia: str = ""
    typ_jednostki: str = ""
    bledy: list[Blad] = field(default_factory=list)
    schemat: str = "klasyczny"   # "klasyczny" | "jpk_sf_v2"

    @property
    def ma_bledy_krytyczne(self) -> bool:
        return any(b.poziom == "KRYTYCZNY" for b in self.bledy)

    @property
    def status(self) -> str:
        if self.ma_bledy_krytyczne:
            return "CZERWONE"
        if any(b.poziom == "OSTRZEŻENIE" for b in self.bledy):
            return "ŻÓŁTE"
        return "ZIELONE"


# ============================================================
# Pomocnicze
# ============================================================

def _znajdz(root: ET.Element, local_name: str) -> Optional[ET.Element]:
    """Pierwszy element o danej lokalnej nazwie (case-insensitive)."""
    target = local_name.lower()
    for el in root.iter():
        local = (el.tag.split("}")[-1] if "}" in el.tag else el.tag).lower()
        if local == target:
            return el
    return None


def _first(root: ET.Element, *names: str) -> Optional[ET.Element]:
    for name in names:
        el = _znajdz(root, name)
        if el is not None:
            return el
    return None


def _tekst(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _decimal(tekst: Optional[str]) -> Optional[Decimal]:
    if not tekst:
        return None
    try:
        return Decimal(tekst.replace(",", ".").replace(" ", "").replace("\xa0", ""))
    except InvalidOperation:
        return None


def _parse_date(tekst: Optional[str]) -> Optional[date]:
    if not tekst:
        return None
    try:
        return date.fromisoformat(tekst.strip())
    except ValueError:
        return None


def _nip_valid(nip: str) -> bool:
    nip = re.sub(r"\D", "", nip)
    if len(nip) != 10:
        return False
    wagi = [6, 5, 7, 2, 3, 4, 5, 6, 7]
    try:
        suma = sum(int(nip[i]) * wagi[i] for i in range(9))
        return (suma % 11) == int(nip[9])
    except (ValueError, IndexError):
        return False


def _regon_valid(regon: str) -> bool:
    regon = re.sub(r"\D", "", regon)
    try:
        if len(regon) == 9:
            wagi = [8, 9, 2, 3, 4, 5, 6, 7]
            suma = sum(int(regon[i]) * wagi[i] for i in range(8))
            return (suma % 11) % 10 == int(regon[8])
        if len(regon) == 14:
            wagi = [2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8]
            suma = sum(int(regon[i]) * wagi[i] for i in range(13))
            return (suma % 11) % 10 == int(regon[13])
    except (ValueError, IndexError):
        pass
    return False


def _child_kwota(parent: Optional[ET.Element], child_name: str = "KwotaA") -> Optional[Decimal]:
    """Pobierz wartość bezpośredniego dziecka o nazwie child_name."""
    if parent is None:
        return None
    target = child_name.lower()
    for c in parent:
        cl = (c.tag.split("}")[-1] if "}" in c.tag else c.tag).lower()
        if cl == target and c.text:
            return _decimal(c.text)
    return None


# ============================================================
# Wykrywanie schematu i typu jednostki
# ============================================================

# Kody sprawozdania charakterystyczne dla JPK_SF v2
JPK_SF_V2_KODY = {
    "sprfinjednostkainnawzlotych",
    "sprfinjednostkainnawtysiącach",
    "sprfinjednostkainnawtysiącach",
    "sprfinjednostkainnawtysiącach",
    "sprfinjednostkamikrowzlotych",
    "sprfinjednostkamikrowtysiącach",
    "sprfinjednostkamalawzlotych",
    "sprfinjednostkamalawtysiącach",
}

TYPY_JEDNOSTEK_LOKAL = {
    "jednostkamikro": "Jednostka mikro",
    "jednostkamala":  "Jednostka mała",
    "jednostkainna":  "Jednostka inna (pełna)",
}


def _wykryj_schemat_i_typ(root: ET.Element) -> tuple[str, str]:
    """Zwraca (schemat, typ_jednostki)."""
    schemat = "klasyczny"
    typ = "Nieznany typ"

    # Sprawdź KodSprawozdania (obecny w JPK_SF v2)
    kod_el = _znajdz(root, "KodSprawozdania")
    if kod_el is not None and kod_el.text:
        kod = kod_el.text.strip().lower()
        if any(k in kod for k in JPK_SF_V2_KODY):
            schemat = "jpk_sf_v2"
        if "mikro" in kod:
            typ = "Jednostka mikro"
        elif "mala" in kod or "mała" in kod:
            typ = "Jednostka mała"
        elif "inna" in kod:
            typ = "Jednostka inna (pełna)"
        return schemat, typ

    # Fallback: sprawdź root tag
    root_local = (root.tag.split("}")[-1] if "}" in root.tag else root.tag).lower()
    for klucz, nazwa in TYPY_JEDNOSTEK_LOKAL.items():
        if klucz in root_local:
            typ = nazwa
            break

    # Sprawdź czy P_1D (NIP w schemacie v2) istnieje → v2
    if _znajdz(root, "P_1D") is not None:
        schemat = "jpk_sf_v2"

    return schemat, typ


# ============================================================
# Główna klasa walidatora
# ============================================================

class WalidatorESprawozdan:

    def waliduj(self, xml_tekst: str) -> WynikWalidacji:
        wynik = WynikWalidacji()
        try:
            root = ET.fromstring(xml_tekst)
        except ET.ParseError as e:
            wynik.bledy.append(Blad("KRYTYCZNY", "STRUKTURA",
                                    "Plik XML jest uszkodzony lub nieprawidłowo sformatowany", str(e)))
            return wynik

        wynik.schemat, wynik.typ_jednostki = _wykryj_schemat_i_typ(root)

        self._waliduj_identyfikacje(root, wynik)
        self._waliduj_daty(root, wynik)
        self._waliduj_kompletnosc(root, wynik)
        self._waliduj_bilans(root, wynik)
        self._waliduj_spojnosc_rzis_bilans(root, wynik)
        return wynik

    # --------------------------------------------------------
    # Identyfikacja
    # --------------------------------------------------------

    def _waliduj_identyfikacje(self, root: ET.Element, wynik: WynikWalidacji):
        v2 = (wynik.schemat == "jpk_sf_v2")

        # --- NIP ---
        # JPK_SF v2: P_1D  |  klasyczny: NIP
        nip_el = _znajdz(root, "P_1D") if v2 else _first(root, "NIP")
        nip_str = _tekst(nip_el)
        if not nip_str:
            wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA",
                                    "Brak NIP podmiotu",
                                    "W schemacie JPK_SF v2 NIP znajduje się w tagu <P_1D>" if v2 else "Oczekiwano tagu <NIP>"))
        else:
            nip = re.sub(r"\D", "", nip_str)
            wynik.podmiot_nip = nip
            if len(nip) != 10:
                wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA",
                                        "NIP ma nieprawidłową liczbę cyfr",
                                        f"znaleziono {len(nip)} cyfr, wymagane 10"))
            elif not _nip_valid(nip):
                wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA",
                                        "NIP nie przechodzi weryfikacji sumy kontrolnej",
                                        f"NIP: {nip}"))

        # --- REGON ---
        # JPK_SF v2: REGON NIE jest wymagany w nagłówku (jest w danych KRS)
        # Klasyczny: REGON wymagany
        if not v2:
            regon_el = _znajdz(root, "REGON")
            regon_str = _tekst(regon_el)
            if not regon_str:
                wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA", "Brak tagu <REGON> lub tag jest pusty"))
            else:
                regon = re.sub(r"\D", "", regon_str)
                if len(regon) not in (9, 14):
                    wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA",
                                            "REGON ma nieprawidłową liczbę cyfr",
                                            f"znaleziono {len(regon)}, wymagane 9 lub 14"))
                elif not _regon_valid(regon):
                    wynik.bledy.append(Blad("OSTRZEŻENIE", "IDENTYFIKACJA",
                                            "REGON nie przechodzi weryfikacji sumy kontrolnej",
                                            f"REGON: {regon}"))

        # --- KRS ---
        # JPK_SF v2: P_1E  |  klasyczny: KRS
        krs_el = _znajdz(root, "P_1E") if v2 else _znajdz(root, "KRS")
        krs_str = _tekst(krs_el)
        if krs_str:
            krs = re.sub(r"\D", "", krs_str)
            if len(krs) != 10:
                wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA",
                                        "KRS ma nieprawidłowy format",
                                        f"znaleziono {len(krs)} cyfr, wymagane 10"))

        # --- Nazwa firmy ---
        nazwa_el = _first(root, "NazwaFirmy", "Nazwa")
        nazwa_str = _tekst(nazwa_el)
        if not nazwa_str:
            wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA",
                                    "Brak nazwy podmiotu (NazwaFirmy / Nazwa)"))
        else:
            wynik.podmiot_nazwa = nazwa_str

        # --- PKD ---
        # JPK_SF v2: KodPKD2007  |  klasyczny: PKD
        pkd_el = _first(root, "KodPKD2007", "PKD")
        if pkd_el is None or not _tekst(pkd_el):
            wynik.bledy.append(Blad("OSTRZEŻENIE", "IDENTYFIKACJA",
                                    "Brak kodu PKD (szukano: KodPKD2007 / PKD)"))

    # --------------------------------------------------------
    # Daty
    # --------------------------------------------------------

    def _waliduj_daty(self, root: ET.Element, wynik: WynikWalidacji):
        data_od_el = _first(root, "OkresOd", "DataOd", "OkresRaportowyOd")
        data_do_el = _first(root, "OkresDo", "DataDo", "OkresRaportoryDo")
        data_sp_el = _first(root, "DataSporzadzenia", "DataSporządzenia")

        data_od_str = _tekst(data_od_el)
        data_do_str = _tekst(data_do_el)
        data_sp_str = _tekst(data_sp_el)

        wynik.okres_od          = data_od_str
        wynik.okres_do          = data_do_str
        wynik.data_sporzadzenia = data_sp_str

        if not data_od_str:
            wynik.bledy.append(Blad("KRYTYCZNY", "DATA", "Brak daty początku okresu (OkresOd)"))
        if not data_do_str:
            wynik.bledy.append(Blad("KRYTYCZNY", "DATA", "Brak daty końca okresu (OkresDo)"))
        if not data_sp_str:
            wynik.bledy.append(Blad("KRYTYCZNY", "DATA", "Brak daty sporządzenia (DataSporzadzenia)"))

        data_od = _parse_date(data_od_str)
        data_do = _parse_date(data_do_str)
        data_sp = _parse_date(data_sp_str)

        if data_od and data_do and data_od >= data_do:
            wynik.bledy.append(Blad("KRYTYCZNY", "DATA",
                                    "Data początku okresu musi być wcześniejsza niż data końca",
                                    f"Od: {data_od_str}, Do: {data_do_str}"))

        if data_do and data_sp:
            if data_sp <= data_do:
                wynik.bledy.append(Blad("KRYTYCZNY", "DATA",
                                        "Data sporządzenia musi być późniejsza niż koniec roku obrotowego",
                                        f"Koniec roku: {data_do_str}, Data sporządzenia: {data_sp_str}"))
            elif data_sp.year == data_do.year:
                wynik.bledy.append(Blad("KRYTYCZNY", "DATA",
                                        f"Data sporządzenia ({data_sp_str}) jest w tym samym roku co koniec okresu "
                                        f"({data_do_str}). Powinna być w roku {data_do.year + 1}.",
                                        "Błąd logiczny — sprawozdanie za zamknięty rok nie może być sporządzone w tym samym roku"))

        if data_sp and data_sp > date.today():
            wynik.bledy.append(Blad("OSTRZEŻENIE", "DATA",
                                    "Data sporządzenia jest w przyszłości",
                                    f"Data sporządzenia: {data_sp_str}, Dziś: {date.today().isoformat()}"))

    # --------------------------------------------------------
    # Kompletność sekcji
    # --------------------------------------------------------

    def _sekcja_istnieje(self, root: ET.Element, nazwy: list[str]) -> bool:
        return any(_znajdz(root, n) is not None for n in nazwy)

    def _waliduj_kompletnosc(self, root: ET.Element, wynik: WynikWalidacji):
        v2 = (wynik.schemat == "jpk_sf_v2")

        # Bilans – zawsze wymagany
        if not self._sekcja_istnieje(root, ["Bilans", "ZestawienieSaldKont", "Aktywa"]):
            wynik.bledy.append(Blad("KRYTYCZNY", "KOMPLETNOŚĆ", "Brak sekcji Bilansu"))

        # RZiS – wymagany dla innych niż mikro
        if "mikro" not in wynik.typ_jednostki.lower():
            rzis_nazwy = ["RZiS", "RachunekZyskow", "RachunekWynikow"]
            if not self._sekcja_istnieje(root, rzis_nazwy):
                wynik.bledy.append(Blad("OSTRZEŻENIE", "KOMPLETNOŚĆ",
                                        f"Brak sekcji RZiS (wymagana dla {wynik.typ_jednostki})",
                                        f"Szukano: {', '.join(rzis_nazwy)}"))

        # Informacja dodatkowa
        # JPK_SF v2: może być jako załącznik PDF (tag Nazwa/Zawartosc w Zalacznik)
        # lub jako tekst w P_7*
        if v2:
            ma_id = (
                self._sekcja_istnieje(root, ["Zalacznik", "Zalaczniki"]) or
                self._sekcja_istnieje(root, ["InformacjaDodatkowa", "Noty", "DodatkoweInformacje"]) or
                _znajdz(root, "P_7A") is not None or
                _znajdz(root, "P_7B") is not None
            )
        else:
            ma_id = self._sekcja_istnieje(root, ["InformacjaDodatkowa", "Noty", "DodatkoweInformacje"])

        if not ma_id and "mikro" not in wynik.typ_jednostki.lower():
            wynik.bledy.append(Blad("OSTRZEŻENIE", "KOMPLETNOŚĆ",
                                    f"Brak Informacji dodatkowej (wymagana dla {wynik.typ_jednostki})",
                                    "Szukano: InformacjaDodatkowa, Noty, Zalacznik, P_7*"))

    # --------------------------------------------------------
    # Bilans
    # --------------------------------------------------------

    def _waliduj_bilans(self, root: ET.Element, wynik: WynikWalidacji):
        v2 = (wynik.schemat == "jpk_sf_v2")

        if v2:
            # JPK_SF v2: <Aktywa><KwotaA> i <Pasywa><KwotaA>
            aktywa_el = _znajdz(root, "Aktywa")
            pasywa_el = _znajdz(root, "Pasywa")
            aktywa = _child_kwota(aktywa_el, "KwotaA")
            pasywa = _child_kwota(pasywa_el, "KwotaA")
        else:
            # Klasyczny: bezpośrednie tagi
            aktywa = self._pobierz_kwote(root, ["AktywaRazem", "SumaAktywow", "AktywaOgolem"])
            pasywa = self._pobierz_kwote(root, ["PasywaRazem", "SumaPasywow", "PasywaOgolem"])

        if aktywa is None and pasywa is None:
            wynik.bledy.append(Blad("OSTRZEŻENIE", "KWOTY",
                                    "Nie znaleziono sum bilansowych — walidacja kwot pominięta"))
            return
        if aktywa is None:
            wynik.bledy.append(Blad("KRYTYCZNY", "KWOTY", "Nie znaleziono sumy Aktywów"))
            return
        if pasywa is None:
            wynik.bledy.append(Blad("KRYTYCZNY", "KWOTY", "Nie znaleziono sumy Pasywów"))
            return

        roznica = abs(aktywa - pasywa)
        if roznica > Decimal("0.01"):
            wynik.bledy.append(Blad("KRYTYCZNY", "KWOTY",
                                    f"Suma Aktywów ≠ Suma Pasywów. Różnica: {roznica:.2f} PLN",
                                    f"Aktywa: {aktywa:.2f}, Pasywa: {pasywa:.2f}"))

    def _pobierz_kwote(self, root: ET.Element, nazwy: list[str]) -> Optional[Decimal]:
        for nazwa in nazwy:
            el = _znajdz(root, nazwa)
            if el is not None and el.text:
                val = _decimal(el.text)
                if val is not None:
                    return val
        return None

    # --------------------------------------------------------
    # RZiS ↔ Bilans (spójność wyniku netto)
    # --------------------------------------------------------

    def _waliduj_spojnosc_rzis_bilans(self, root: ET.Element, wynik: WynikWalidacji):
        v2 = (wynik.schemat == "jpk_sf_v2")

        if v2:
            # RZiS > RZiSPor > L > KwotaA  (pozycja L = Zysk/strata netto)
            l_el = _znajdz(root, "L")
            wynik_rzis = _child_kwota(l_el, "KwotaA") if l_el is not None else None

            # Bilans: Pasywa_A_VII > KwotaA (Zysk/strata netto w KW)
            pa7_el = _first(root, "Pasywa_A_VI", "Pasywa_A_VII", "Pasywa_A_VIII")
            wynik_bilans = _child_kwota(pa7_el, "KwotaA") if pa7_el is not None else None
        else:
            wynik_rzis   = self._pobierz_kwote(root, ["WynikFinansowyNetto", "ZyskStrataNetto", "WynikNetto"])
            wynik_bilans = self._pobierz_kwote(root, ["ZyskStrata", "ZyskStrataNetto", "KapitalWlasnyWynik"])

        if wynik_rzis is None or wynik_bilans is None:
            return  # nie można porównać

        if abs(wynik_rzis - wynik_bilans) > Decimal("0.01"):
            wynik.bledy.append(Blad("KRYTYCZNY", "LOGIKA",
                                    "Wynik finansowy netto z RZiS różni się od pozycji Zysk/strata netto w Bilansie (Pasywa A.VII)",
                                    f"RZiS: {wynik_rzis:.2f}, Bilans/KW: {wynik_bilans:.2f}, "
                                    f"różnica: {abs(wynik_rzis - wynik_bilans):.2f}"))


# ============================================================
# Raport tekstowy
# ============================================================

def generuj_raport(wynik: WynikWalidacji) -> str:
    linie = [
        "=" * 70,
        "RAPORT WALIDACJI e-SPRAWOZDANIA FINANSOWEGO",
        "=" * 70,
        f"Podmiot:            {wynik.podmiot_nazwa or 'BRAK'}",
        f"NIP:                {wynik.podmiot_nip or 'BRAK'}",
        f"Typ jednostki:      {wynik.typ_jednostki or 'NIEZNANY'}",
        f"Schemat XML:        {wynik.schemat}",
        f"Okres:              {wynik.okres_od} — {wynik.okres_do}",
        f"Data sporządzenia:  {wynik.data_sporzadzenia or 'BRAK'}",
        "-" * 70,
    ]
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


# ============================================================
# Streamlit UI
# ============================================================

st.set_page_config(
    page_title="Walidator e-Sprawozdań",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="collapsed",
)

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
.info-card .value { font-size:1rem; font-weight:600; color:#111827; margin-top:0.2rem; word-break:break-all; }

.schemat-badge { display:inline-block; background:#ede9fe; color:#5b21b6; font-size:0.75rem;
                 padding:0.2rem 0.6rem; border-radius:4px; font-weight:600; margin-bottom:1rem; }

.blad-krytyczny  { background:#fff1f2; border:1px solid #fecdd3; border-left:4px solid #ef4444;
                   border-radius:6px; padding:0.9rem 1.1rem; margin:0.5rem 0; }
.blad-ostrzezenie{ background:#fffbeb; border:1px solid #fde68a;  border-left:4px solid #f59e0b;
                   border-radius:6px; padding:0.9rem 1.1rem; margin:0.5rem 0; }
.blad-krytyczny  .badge { background:#ef4444; color:white; font-size:0.7rem;
                           padding:0.15rem 0.5rem; border-radius:4px; font-weight:700; }
.blad-ostrzezenie .badge{ background:#f59e0b; color:white; font-size:0.7rem;
                           padding:0.15rem 0.5rem; border-radius:4px; font-weight:700; }
.blad-kat       { font-size:0.78rem; color:#6b7280; margin-left:0.5rem; }
.blad-opis      { font-weight:600; color:#111827; margin:0.3rem 0 0 0; font-size:0.92rem; }
.blad-szczegoly { color:#6b7280; font-size:0.85rem; margin:0.2rem 0 0 0; }

.stat-pill   { display:inline-block; padding:0.3rem 0.8rem; border-radius:20px;
               font-size:0.82rem; font-weight:600; margin:0.2rem; }
.pill-red    { background:#fee2e2; color:#b91c1c; }
.pill-yellow { background:#fef3c7; color:#92400e; }
.divider     { border:none; border-top:1px solid #e5e7eb; margin:1.5rem 0; }
.raport-txt  { background:#1e293b; color:#e2e8f0; font-family:'Courier New',monospace;
               font-size:0.82rem; padding:1.5rem; border-radius:8px;
               white-space:pre-wrap; word-break:break-word; max-height:420px; overflow-y:auto; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="header-box">
    <h1>📋 Walidator e-Sprawozdań Finansowych</h1>
    <p>Głęboka walidacja logiczna, merytoryczna i kompletności danych XML &mdash;
       obsługuje schemat klasyczny oraz JPK_SF v2 (SprFinJednostkaInna, JednostkaMikro, JednostkaMała)</p>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns([2, 1])
with col1:
    plik = st.file_uploader("Wgraj plik e-Sprawozdania (XML)", type=["xml"],
                             help="Obsługuje oba schematy MF: klasyczny i JPK_SF v2")
with col2:
    st.markdown("<br>", unsafe_allow_html=True)
    st.info("**Sprawdzane reguły:**\n"
            "- Auto-detekcja schematu XML (klasyczny / JPK_SF v2)\n"
            "- Logika dat (rok obrotowy vs data sporządzenia)\n"
            "- NIP (suma kontrolna) / KRS / REGON\n"
            "- Kompletność sekcji (Bilans, RZiS, Inf. dodatkowa)\n"
            "- Aktywa = Pasywa\n"
            "- Wynik netto RZiS = Wynik netto w KW (Bilans)")

if plik is not None:
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    try:
        xml_bytes = plik.read()
        try:
            xml_tekst = xml_bytes.decode("utf-8")
        except UnicodeDecodeError:
            xml_tekst = xml_bytes.decode("windows-1250", errors="replace")

        wynik = WalidatorESprawozdan().waliduj(xml_tekst)
        krity   = [b for b in wynik.bledy if b.poziom == "KRYTYCZNY"]
        ostrzeż = [b for b in wynik.bledy if b.poziom == "OSTRZEŻENIE"]

        # Schemat badge
        schemat_label = "JPK_SF v2 (nowy schemat MF)" if wynik.schemat == "jpk_sf_v2" else "Schemat klasyczny"
        st.markdown(f'<span class="schemat-badge">🔍 Wykryty schemat: {schemat_label}</span>',
                    unsafe_allow_html=True)

        # Status banner
        if wynik.status == "ZIELONE":
            st.markdown("""<div class="status-green">
                <h3>✅ ZIELONE ŚWIATŁO — Plik jest poprawny</h3>
                <p>Nie wykryto błędów krytycznych ani ostrzeżeń. Plik można wysłać do KRS/KAS.</p>
            </div>""", unsafe_allow_html=True)
        elif wynik.status == "ŻÓŁTE":
            st.markdown(f"""<div class="status-yellow">
                <h3>⚠️ ŻÓŁTE ŚWIATŁO — Wykryto ostrzeżenia</h3>
                <p>Brak błędów krytycznych, ale znaleziono {len(ostrzeż)} ostrzeżeń. Zalecana weryfikacja.</p>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown(f"""<div class="status-red">
                <h3>🔴 CZERWONE ŚWIATŁO — Wykryto błędy krytyczne</h3>
                <p>Znaleziono {len(krity)} błędów krytycznych i {len(ostrzeż)} ostrzeżeń.</p>
            </div>""", unsafe_allow_html=True)

        # Info o podmiocie
        st.markdown(f"""
        <div class="info-grid">
            <div class="info-card"><div class="label">Podmiot</div>
                <div class="value">{wynik.podmiot_nazwa or '—'}</div></div>
            <div class="info-card"><div class="label">NIP</div>
                <div class="value">{wynik.podmiot_nip or '—'}</div></div>
            <div class="info-card"><div class="label">Typ jednostki</div>
                <div class="value">{wynik.typ_jednostki or '—'}</div></div>
            <div class="info-card"><div class="label">Okres od</div>
                <div class="value">{wynik.okres_od or '—'}</div></div>
            <div class="info-card"><div class="label">Okres do</div>
                <div class="value">{wynik.okres_do or '—'}</div></div>
            <div class="info-card"><div class="label">Data sporządzenia</div>
                <div class="value">{wynik.data_sporzadzenia or '—'}</div></div>
        </div>""", unsafe_allow_html=True)

        if wynik.bledy:
            st.markdown(
                f'<span class="stat-pill pill-red">🔴 Krytyczne: {len(krity)}</span>'
                f'<span class="stat-pill pill-yellow">⚠️ Ostrzeżenia: {len(ostrzeż)}</span>',
                unsafe_allow_html=True)
            st.markdown("<br>", unsafe_allow_html=True)

        if krity:
            st.subheader("🔴 Błędy krytyczne")
            for i, b in enumerate(krity, 1):
                sz = f"<p class='blad-szczegoly'>{b.szczegoly}</p>" if b.szczegoly else ""
                st.markdown(f"""<div class="blad-krytyczny">
                    <span class="badge">KRYTYCZNY</span><span class="blad-kat">{b.kategoria}</span>
                    <p class="blad-opis">{i}. {b.opis}</p>{sz}</div>""", unsafe_allow_html=True)

        if ostrzeż:
            st.subheader("⚠️ Ostrzeżenia")
            for i, b in enumerate(ostrzeż, 1):
                sz = f"<p class='blad-szczegoly'>{b.szczegoly}</p>" if b.szczegoly else ""
                st.markdown(f"""<div class="blad-ostrzezenie">
                    <span class="badge">OSTRZEŻENIE</span><span class="blad-kat">{b.kategoria}</span>
                    <p class="blad-opis">{i}. {b.opis}</p>{sz}</div>""", unsafe_allow_html=True)

        if not wynik.bledy:
            st.success("Brak jakichkolwiek błędów i ostrzeżeń.")

        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        st.subheader("📄 Eksport raportu")
        raport = generuj_raport(wynik)
        st.markdown(f'<div class="raport-txt">{raport}</div>', unsafe_allow_html=True)
        st.download_button("⬇️ Pobierz raport .txt",
                           data=raport.encode("utf-8"),
                           file_name=f"walidacja_{wynik.podmiot_nip or 'brak_nip'}.txt",
                           mime="text/plain")

    except Exception as e:
        st.error(f"Nieoczekiwany błąd podczas walidacji: {e}")
        st.exception(e)

else:
    st.markdown("""
    <div style="background:white; border:2px dashed #d1d5db; border-radius:12px;
                padding:3rem; text-align:center; margin:1rem 0;">
        <p style="font-size:2.5rem; margin:0;">📁</p>
        <p style="font-weight:600; color:#374151; margin:0.5rem 0;">Przeciągnij plik XML lub kliknij przycisk powyżej</p>
        <p style="color:#9ca3af; font-size:0.88rem; margin:0;">
            Obsługuje schemat klasyczny i JPK_SF v2 (MF 2024/2025)</p>
    </div>""", unsafe_allow_html=True)
