import numpy as np
import pandas as pd
from datetime import date, datetime
import QuantLib as ql


# Methoden zur Restlaufzeit Berechnung - Anfang
def _to_ql_date(value):
    if value is None:
        return None
    if isinstance(value, ql.Date):
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"Invalid date string '{value}'. Erwartet ISO-Format YYYY-MM-DD "
                "(z. B. maturity statt mat_sect uebergeben)."
            ) from exc
        return ql.Date(parsed.day, parsed.month, parsed.year)
    if isinstance(value, np.datetime64):
        value = pd.Timestamp(value)
    if isinstance(value, pd.Timestamp):
        return ql.Date(value.day, value.month, value.year)
    if isinstance(value, datetime):
        return ql.Date(value.day, value.month, value.year)
    if isinstance(value, date):
        return ql.Date(value.day, value.month, value.year)
    if hasattr(value, 'to_pydatetime'):
        converted = value.to_pydatetime()
        return ql.Date(converted.day, converted.month, converted.year)
    if hasattr(value, 'year') and hasattr(value, 'month') and hasattr(value, 'day'):
        return ql.Date(int(value.day), int(value.month), int(value.year))
    raise TypeError("Date input muss None, datetime.date, datetime, ISO-String, Pandas Timestamp, numpy.datetime64 oder QuantLib.Date sein.")

def get_year_fraction_anniversary_old(start_date, end_date):
    """
    Urspruengliche Anniversary-Methode:
    Ganze Kalenderjahre + Resttage / Tage des exakten Folgejahres.
    """

    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    if start_date > end_date:
        return -get_year_fraction_anniversary_old(end_date, start_date)
    if start_date == end_date:
        return 0.0

    years = end_date.year - start_date.year
    anniversary = start_date.replace(year=end_date.year)
    if anniversary > end_date:
        years -= 1
        prev_anniversary = start_date.replace(year=end_date.year - 1)
        next_anniversary = anniversary
    else:
        prev_anniversary = anniversary
        next_anniversary = start_date.replace(year=end_date.year + 1)

    remaining_days = (end_date - prev_anniversary).days
    days_in_year = (next_anniversary - prev_anniversary).days
    return years + (remaining_days / days_in_year)

def get_year_fraction_anniversary(start_date, end_date, freq=1):
    """
    Methode 1: Exakte Perioden gemaess Kuponfrequenz.

    - freq=1: ganze Kalenderjahre + Resttage / Tage des exakten Folgejahres.
    - freq=2: ganze Halbjahre + Resttage / Tage der exakten Folge-Halbjahresperiode.
    - freq=4: ganze Quartale + Resttage / Tage der exakten Folge-Quartalsperiode.

    Vorteil: Volle Kuponperioden bleiben exakt erhalten, also z. B.
    bei freq=2 der Zeitraum 03.08.2026 -> 03.02.2027 = 0.5 Jahre.
    """


    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    if start_date > end_date:
        return -get_year_fraction_anniversary(end_date, start_date, freq=freq)
    if start_date == end_date:
        return 0.0

    freq_int = int(freq)
    if freq_int <= 0:
        raise ValueError("freq muss > 0 sein.")
    if 12 % freq_int != 0:
        raise ValueError("freq muss ein Teiler von 12 sein, z. B. 1, 2, 3, 4, 6 oder 12.")

    if end_date <= start_date:
        return 0.0 if end_date  == start_date else -get_year_fraction_anniversary(end_date, start_date, freq=freq_int)

    period_months = 12 // freq_int
    current_period_start = start_date
    completed_periods = 0

    while True:
        next_period_start = current_period_start + pd.DateOffset(months=period_months)
        if next_period_start <= end_date:
            completed_periods += 1
            current_period_start = next_period_start
        else:
            break

    next_period_start = current_period_start + pd.DateOffset(months=period_months)
    remaining_days = (end_date - current_period_start).days
    days_in_period = (next_period_start - current_period_start).days

    return completed_periods / freq_int + (remaining_days / days_in_period) / freq_int

def get_year_fraction_bloomberg(start_date, end_date):
    """
    Methode 2: Bloomberg / Act/365.25 Standard (Gesamte Tage / 365.25).
    Vorteil: Einfach, schnell und von Bloomberg-Terminals für YTM/Duration verwendet.
    """
    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    if start_date > end_date:
        return -get_year_fraction_bloomberg(end_date, start_date)
    if start_date == end_date:
        return 0.0


    days = (end_date - start_date).days
    return days / 365.25


def get_year_fraction_isda(start_date, end_date):
    """
    QuantLib Actual/Actual (ISDA) Year Fraction.
    """

    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    if start_date > end_date:
        return -get_year_fraction_isda(end_date, start_date)
    if start_date == end_date:
        return 0.0


    d1 = ql.Date(start_date.day, start_date.month, start_date.year)
    d2 = ql.Date(end_date.day, end_date.month, end_date.year)

    return ql.ActualActual(ql.ActualActual.ISDA).yearFraction(d1, d2, d1, d2)


def get_year_fraction_actual365(start_date, end_date):
    """
    QuantLib Actual/365 Fixed Year Fraction.
    """

    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    if start_date > end_date:
        return -get_year_fraction_actual365(end_date, start_date)
    if start_date == end_date:
        return 0.0



    d1 = ql.Date(start_date.day, start_date.month, start_date.year)
    d2 = ql.Date(end_date.day, end_date.month, end_date.year)

    return ql.Actual365Fixed().yearFraction(d1, d2)


def get_year_fraction_actual360(start_date, end_date):
    """
    QuantLib Actual/360 Year Fraction.
    """

    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    if start_date > end_date:
        return -get_year_fraction_actual360(end_date, start_date)
    if start_date == end_date:
        return 0.0



    d1 = ql.Date(start_date.day, start_date.month, start_date.year)
    d2 = ql.Date(end_date.day, end_date.month, end_date.year)

    return ql.Actual360().yearFraction(d1, d2)


def get_year_fraction_quantlib(start_date, end_date, freq=1):
    """
    QuantLib Actual/Actual (Bond) Year Fraction mit Referenzperiode aus freq.

    Formel:
        RLZ = ActualActual(Bond).yearFraction(start_date, end_date, ref_start, ref_end)
    """

    ql_start = _to_ql_date(start_date)
    ql_end = _to_ql_date(end_date)

    if ql_start is None or ql_end is None:
        raise ValueError("start_date und end_date duerfen nicht None sein.")
    if ql_end <= ql_start:
        return 0.0 if ql_end == ql_start else -get_year_fraction_quantlib(end_date, start_date, freq=freq)

    freq_int = int(freq)
    if freq_int not in [1, 2, 4, 12]:
        raise ValueError("freq muss eine von [1, 2, 4, 12] sein.")

    tenor = ql.Period(int(round(12 / freq_int)), ql.Months)
    ref_start = ql_start
    ref_end = ql_start + tenor

    day_count = ql.ActualActual(ql.ActualActual.Bond)
    return day_count.yearFraction(ql_start, ql_end, ref_start, ref_end)


def rlz(start_date, end_date, method='bond', freq=1):
    """
    Grundfunktion zur Berechnung der Restlaufzeit (Year Fraction).
    
    Parameters:
      - start_date : Start- bzw. Settlement-Datum
            - end_date   : Faelligkeitsdatum (Maturity)
            - method     : 'anniversary', 'anniversary_old', 'bloomberg', 'isda',
                                         'quantlib'/'bond', 'actual365', 'actual360'
            - freq       : Kuponfrequenz pro Jahr fuer anniversary und quantlib/bond,
                                         z. B. 1, 2, 4, 12
    """

    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date)

    if start_date > end_date:
        return -rlz(end_date, start_date, method=method, freq=freq)
    if start_date == end_date:
        return 0.0

    method_lower = str(method).lower()

    if method_lower in ['anniversary', 'method1', 'm1']:
        return get_year_fraction_anniversary(start_date, end_date, freq=freq)
    if method_lower in ['anniversary_old', 'method1_old', 'm1_old']:
        return get_year_fraction_anniversary_old(start_date, end_date)
    if method_lower in ['bloomberg', 'method2', 'm2']:
        return get_year_fraction_bloomberg(start_date, end_date)
    if method_lower == 'isda':
        return get_year_fraction_isda(start_date, end_date)
    if method_lower in ['quantlib', 'bond']:
        return get_year_fraction_quantlib(start_date, end_date, freq=freq)
    if method_lower in ['actual365', 'act365']:
        return get_year_fraction_actual365(start_date, end_date)
    if method_lower in ['actual360', 'act360']:
        return get_year_fraction_actual360(start_date, end_date)

    raise ValueError(f"Unbekannte Methode: {method}")
# Methoden zur Restlaufzeit Berechnung - Ende
