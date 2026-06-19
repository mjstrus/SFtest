"""
Walidator e-Sprawozdań Finansowych (XML)
Obsługuje: jednostki mikro, małe, inne (pełne)
"""

from __future__ import annotations
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional
import re


# ---------------------------------------------------------------------------
# Struktury danych
# ---------------------------------------------------------------------------

@dataclass
class Blad:
    poziom: str          # KRYTYCZNY | OSTRZEŻENIE | INFO
    kategoria: str       # DATA | IDENTYFIKACJA | KWOTY | KOMPLETNOŚĆ | LOGIKA
    opis: str
    szczegoly: str = ""

    def __str__(self):
        suffix = f" — {self.szczegoly}" if self.szczegoly else ""
        return f"[{self.poziom}] {self.kategoria}: {self.opis}{suffix}"


@dataclass
class WynikWalidacji:
    podmiot_nazwa: str = ""
    podmiot_nip: str = ""
    okres_od: str = ""
    okres_do: str = ""
    data_sporzadzenia: str = ""
    typ_jednostki: str = ""
    bledy: list[Blad] = field(default_factory=list)

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


# ---------------------------------------------------------------------------
# Pomocnicze
# ---------------------------------------------------------------------------

NS_MAP = {
    # Różne przestrzenie nazw używane przez MF w zależności od roku/wersji
    "sf": "http://www.mf.gov.pl/schematy/SF",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

def _find_tekst(root: ET.Element, *ścieżki: str) -> Optional[str]:
    """Szuka tekstu elementu po wielu możliwych ścieżkach (ignorując namespace)."""
    for ścieżka in ścieżki:
        for el in root.iter():
            # porównanie po lokalnej nazwie (bez namespace)
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            parts = ścieżka.split("/")
            if local == parts[-1] and el.text and el.text.strip():
                return el.text.strip()
    return None


def _znajdz_element(root: ET.Element, local_name: str) -> Optional[ET.Element]:
    """Zwraca pierwszy element o danej lokalnej nazwie tagu."""
    target = local_name.lower()
    for el in root.iter():
        local = (el.tag.split("}")[-1] if "}" in el.tag else el.tag).lower()
        if local == target:
            return el
    return None


def _wszystkie_elementy(root: ET.Element, local_name: str) -> list[ET.Element]:
    result = []
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if local == local_name:
            result.append(el)
    return result


def _decimal(tekst: Optional[str]) -> Optional[Decimal]:
    if tekst is None:
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
    suma = sum(int(nip[i]) * wagi[i] for i in range(9))
    return (suma % 11) == int(nip[9])


def _regon_valid(regon: str) -> bool:
    regon = re.sub(r"\D", "", regon)
    if len(regon) == 9:
        wagi = [8, 9, 2, 3, 4, 5, 6, 7]
        suma = sum(int(regon[i]) * wagi[i] for i in range(8))
        return (suma % 11) % 10 == int(regon[8])
    if len(regon) == 14:
        wagi = [2, 4, 8, 5, 0, 9, 7, 3, 6, 1, 2, 4, 8]
        suma = sum(int(regon[i]) * wagi[i] for i in range(13))
        return (suma % 11) % 10 == int(regon[13])
    return False


# ---------------------------------------------------------------------------
# Wykrywanie typu jednostki
# ---------------------------------------------------------------------------

TYPY_JEDNOSTEK = {
    "JednostkaMikro": "Jednostka mikro",
    "JednostkaMALA": "Jednostka mała",
    "JednostkaMala": "Jednostka mała",
    "JednostkaInna": "Jednostka inna (pełna)",
    "JednostkaInnaNGO": "Jednostka inna – NGO",
    "SprawozdanieSkonsolidowane": "Sprawozdanie skonsolidowane",
}

def _wykryj_typ(root: ET.Element) -> str:
    root_local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    for klucz, nazwa in TYPY_JEDNOSTEK.items():
        if klucz.lower() in root_local.lower():
            return nazwa
    # Sprawdź po atrybucie xsi:type lub strukturze
    for el in root.iter():
        local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        for klucz, nazwa in TYPY_JEDNOSTEK.items():
            if klucz.lower() in local.lower():
                return nazwa
    return "Nieznany typ"


# ---------------------------------------------------------------------------
# Główna klasa walidatora
# ---------------------------------------------------------------------------

class WalidatorESprawozdan:

    def waliduj(self, xml_tekst: str) -> WynikWalidacji:
        wynik = WynikWalidacji()
        try:
            root = ET.fromstring(xml_tekst)
        except ET.ParseError as e:
            wynik.bledy.append(Blad(
                poziom="KRYTYCZNY",
                kategoria="STRUKTURA",
                opis="Plik XML jest uszkodzony lub nieprawidłowo sformatowany",
                szczegoly=str(e)
            ))
            return wynik

        wynik.typ_jednostki = _wykryj_typ(root)

        self._waliduj_identyfikacje(root, wynik)
        self._waliduj_daty(root, wynik)
        self._waliduj_kompletnosc(root, wynik)
        self._waliduj_bilans(root, wynik)
        self._waliduj_rzis(root, wynik)
        self._waliduj_spojnosc_rzis_bilans(root, wynik)

        return wynik

    # ------------------------------------------------------------------
    # 1. Identyfikacja podmiotu
    # ------------------------------------------------------------------

    def _waliduj_identyfikacje(self, root: ET.Element, wynik: WynikWalidacji):
        # NIP
        nip_el = _znajdz_element(root, "NIP")
        if nip_el is None or not (nip_el.text or "").strip():
            wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA", "Brak tagu <NIP> lub tag jest pusty"))
        else:
            nip = re.sub(r"\D", "", nip_el.text.strip())
            wynik.podmiot_nip = nip
            if len(nip) != 10:
                wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA", "NIP ma nieprawidłową liczbę cyfr", f"znaleziono {len(nip)} cyfr, wymagane 10"))
            elif not _nip_valid(nip):
                wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA", "NIP nie przechodzi weryfikacji sumy kontrolnej", f"NIP: {nip}"))

        # REGON
        regon_el = _znajdz_element(root, "REGON")
        if regon_el is None or not (regon_el.text or "").strip():
            wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA", "Brak tagu <REGON> lub tag jest pusty"))
        else:
            regon = re.sub(r"\D", "", regon_el.text.strip())
            if len(regon) not in (9, 14):
                wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA", "REGON ma nieprawidłową liczbę cyfr", f"znaleziono {len(regon)}, wymagane 9 lub 14"))
            elif not _regon_valid(regon):
                wynik.bledy.append(Blad("OSTRZEŻENIE", "IDENTYFIKACJA", "REGON nie przechodzi weryfikacji sumy kontrolnej", f"REGON: {regon}"))

        # KRS (opcjonalny, ale jeśli jest – sprawdź format)
        krs_el = _znajdz_element(root, "KRS")
        if krs_el is not None and (krs_el.text or "").strip():
            krs = re.sub(r"\D", "", krs_el.text.strip())
            if len(krs) != 10:
                wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA", "KRS ma nieprawidłowy format", f"znaleziono {len(krs)} cyfr, wymagane 10"))

        # Nazwa firmy
        nazwa_el = _znajdz_element(root, "NazwaFirmy")
        if nazwa_el is None:
            nazwa_el = _znajdz_element(root, "Nazwa")
        if nazwa_el is None or not (nazwa_el.text or "").strip():
            wynik.bledy.append(Blad("KRYTYCZNY", "IDENTYFIKACJA", "Brak nazwy podmiotu (NazwaFirmy / Nazwa)"))
        else:
            wynik.podmiot_nazwa = nazwa_el.text.strip()

        # PKD
        pkd_el = _znajdz_element(root, "PKD")
        if pkd_el is None or not (pkd_el.text or "").strip():
            wynik.bledy.append(Blad("OSTRZEŻENIE", "IDENTYFIKACJA", "Brak kodu PKD lub tag jest pusty"))

    # ------------------------------------------------------------------
    # 2. Daty
    # ------------------------------------------------------------------

    def _waliduj_daty(self, root: ET.Element, wynik: WynikWalidacji):
        # Szukamy dat pod różnymi możliwymi nazwami
        def _first(*names):
            for n in names:
                el = _znajdz_element(root, n)
                if el is not None:
                    return el
            return None
        data_od_el = _first("OkresOd", "DataOd", "OkresRaportowyOd")
        data_do_el = _first("OkresDo", "DataDo", "OkresRaportoryDo")
        data_sporzadzenia_el = _first("DataSporzadzenia", "DataSporządzenia")

        data_od_str = (data_od_el.text or "").strip() if data_od_el is not None else None
        data_do_str = (data_do_el.text or "").strip() if data_do_el is not None else None
        data_sp_str = (data_sporzadzenia_el.text or "").strip() if data_sporzadzenia_el is not None else None

        wynik.okres_od = data_od_str or ""
        wynik.okres_do = data_do_str or ""
        wynik.data_sporzadzenia = data_sp_str or ""

        if not data_od_str:
            wynik.bledy.append(Blad("KRYTYCZNY", "DATA", "Brak daty początku okresu sprawozdawczego (OkresOd)"))
        if not data_do_str:
            wynik.bledy.append(Blad("KRYTYCZNY", "DATA", "Brak daty końca okresu sprawozdawczego (OkresDo)"))
        if not data_sp_str:
            wynik.bledy.append(Blad("KRYTYCZNY", "DATA", "Brak daty sporządzenia sprawozdania (DataSporzadzenia)"))

        data_od = _parse_date(data_od_str)
        data_do = _parse_date(data_do_str)
        data_sp = _parse_date(data_sp_str)

        if data_od and data_do:
            if data_od >= data_do:
                wynik.bledy.append(Blad("KRYTYCZNY", "DATA", "Data początku okresu musi być wcześniejsza niż data końca",
                                        f"Od: {data_od_str}, Do: {data_do_str}"))

        if data_do and data_sp:
            if data_sp <= data_do:
                wynik.bledy.append(Blad("KRYTYCZNY", "DATA",
                                        "Data sporządzenia musi być późniejsza niż koniec roku obrotowego",
                                        f"Koniec roku: {data_do_str}, Data sporządzenia: {data_sp_str}"))
            # Kluczowa reguła logiczna: zamknięty rok obrotowy → data sporządzenia rok kolejny
            if data_do.year == data_do.year and data_sp.year == data_do.year:
                wynik.bledy.append(Blad("KRYTYCZNY", "DATA",
                                        f"Data sporządzenia ({data_sp_str}) jest w tym samym roku co koniec okresu ({data_do_str}). "
                                        f"Dla roku obrotowego kończącego się {data_do_str}, data sporządzenia powinna być w roku {data_do.year + 1}.",
                                        "Błąd logiczny — sprawozdanie za zamknięty rok nie może być sporządzone w tym samym roku"))

        # Sprawdź czy data sporządzenia nie jest w przyszłości
        if data_sp and data_sp > date.today():
            wynik.bledy.append(Blad("OSTRZEŻENIE", "DATA",
                                    "Data sporządzenia jest w przyszłości",
                                    f"Data sporządzenia: {data_sp_str}, Dziś: {date.today().isoformat()}"))

    # ------------------------------------------------------------------
    # 3. Kompletność sekcji
    # ------------------------------------------------------------------

    WYMAGANE_SEKCJE_WSZYSTKIE = [
        ("Wprowadzenie", ["Wprowadzenie", "Naglowek", "DaneJednostki"]),
        ("Bilans", ["Bilans", "ZestawienieSaldKont"]),
    ]

    WYMAGANE_SEKCJE_PELNE = [
        ("RZiS", ["RachunekZyskow", "RZiS", "RachunekWynikow"]),
        ("Informacja dodatkowa", ["InformacjaDodatkowa", "Noty", "DodatkoweInformacje"]),
    ]

    def _sekcja_istnieje(self, root: ET.Element, mozliwe_nazwy: list[str]) -> bool:
        for nazwa in mozliwe_nazwy:
            el = _znajdz_element(root, nazwa)
            if el is not None:
                return True
        return False

    def _waliduj_kompletnosc(self, root: ET.Element, wynik: WynikWalidacji):
        for opis, nazwy in self.WYMAGANE_SEKCJE_WSZYSTKIE:
            if not self._sekcja_istnieje(root, nazwy):
                wynik.bledy.append(Blad("KRYTYCZNY", "KOMPLETNOŚĆ",
                                        f"Brak sekcji: {opis}",
                                        f"Szukano tagów: {', '.join(nazwy)}"))

        # Dla jednostek innych niż mikro sprawdzamy dodatkowe sekcje
        if "mikro" not in wynik.typ_jednostki.lower():
            for opis, nazwy in self.WYMAGANE_SEKCJE_PELNE:
                if not self._sekcja_istnieje(root, nazwy):
                    wynik.bledy.append(Blad("OSTRZEŻENIE", "KOMPLETNOŚĆ",
                                            f"Brak sekcji (wymagana dla {wynik.typ_jednostki}): {opis}",
                                            f"Szukano tagów: {', '.join(nazwy)}"))

    # ------------------------------------------------------------------
    # 4. Bilans – spójność sum
    # ------------------------------------------------------------------

    SUMY_AKTYWOW = [
        "AktywaRazem", "SumaAktywow", "AktywaOgolem",
        "A_AktywaRazem", "Aktywa_Razem"
    ]
    SUMY_PASYWOW = [
        "PasywaRazem", "SumaPasywow", "PasywaOgolem",
        "A_PasywaRazem", "Pasywa_Razem"
    ]

    def _pobierz_kwote(self, root: ET.Element, mozliwe_nazwy: list[str]) -> Optional[Decimal]:
        for nazwa in mozliwe_nazwy:
            el = _znajdz_element(root, nazwa)
            if el is not None and el.text:
                val = _decimal(el.text)
                if val is not None:
                    return val
        return None

    def _waliduj_bilans(self, root: ET.Element, wynik: WynikWalidacji):
        aktywa = self._pobierz_kwote(root, self.SUMY_AKTYWOW)
        pasywa = self._pobierz_kwote(root, self.SUMY_PASYWOW)

        if aktywa is None and pasywa is None:
            wynik.bledy.append(Blad("OSTRZEŻENIE", "KWOTY",
                                    "Nie znaleziono sum bilansowych (AktywaRazem / PasywaRazem) — walidacja kwot pominięta"))
            return

        if aktywa is None:
            wynik.bledy.append(Blad("KRYTYCZNY", "KWOTY", "Nie znaleziono sumy Aktywów w bilansie"))
        if pasywa is None:
            wynik.bledy.append(Blad("KRYTYCZNY", "KWOTY", "Nie znaleziono sumy Pasywów w bilansie"))

        if aktywa is not None and pasywa is not None:
            roznica = abs(aktywa - pasywa)
            if roznica > Decimal("0.01"):
                wynik.bledy.append(Blad("KRYTYCZNY", "KWOTY",
                                        f"Suma Aktywów ≠ Suma Pasywów. Różnica: {roznica:.2f} PLN",
                                        f"Aktywa: {aktywa:.2f}, Pasywa: {pasywa:.2f}"))

    # ------------------------------------------------------------------
    # 5. RZiS – wynik netto
    # ------------------------------------------------------------------

    WYNIK_RZIS = [
        "WynikFinansowyNetto", "ZyskStrataNetto", "WynikNetto",
        "F_WynikNetto", "ZyskStrata"
    ]
    WYNIK_BILANS_KW = [
        "ZyskStrata", "ZyskStrataNetto", "WynikFinansowyBilans",
        "KapitalWlasnyWynik", "WynikNettoKapital"
    ]

    def _waliduj_rzis(self, root: ET.Element, wynik: WynikWalidacji):
        """Sprawdza czy pozycje RZiS są kompletne (brak pustych tagów)."""
        rzis_el = None
        for nazwa in ["RachunekZyskow", "RZiS", "RachunekWynikow"]:
            rzis_el = _znajdz_element(root, nazwa)
            if rzis_el is not None:
                break

        if rzis_el is None:
            return  # brak RZiS obsłużony w kompletności

        puste = []
        for el in rzis_el.iter():
            local = el.tag.split("}")[-1] if "}" in el.tag else el.tag
            if not list(el) and (el.text is None or not el.text.strip()):
                puste.append(local)

        if puste:
            wynik.bledy.append(Blad("OSTRZEŻENIE", "KWOTY",
                                    f"Znaleziono {len(puste)} pustych tagów w sekcji RZiS",
                                    f"Przykłady: {', '.join(puste[:5])}{'...' if len(puste) > 5 else ''}"))

    def _waliduj_spojnosc_rzis_bilans(self, root: ET.Element, wynik: WynikWalidacji):
        """Wynik netto z RZiS musi być równy pozycji w bilansie."""
        wynik_rzis = self._pobierz_kwote(root, self.WYNIK_RZIS)
        wynik_bilans = self._pobierz_kwote(root, self.WYNIK_BILANS_KW)

        if wynik_rzis is None or wynik_bilans is None:
            return  # nie można porównać

        if abs(wynik_rzis - wynik_bilans) > Decimal("0.01"):
            wynik.bledy.append(Blad("KRYTYCZNY", "LOGIKA",
                                    "Wynik finansowy netto z RZiS różni się od pozycji w Kapitale własnym (Bilans)",
                                    f"RZiS: {wynik_rzis:.2f}, Bilans/KW: {wynik_bilans:.2f}, różnica: {abs(wynik_rzis - wynik_bilans):.2f}"))
