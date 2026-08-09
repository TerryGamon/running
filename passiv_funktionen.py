import numpy as np
import plotnine as p9
import math
from pathlib import Path
import pandas as pd
import os
from datetime import date, timedelta
import math
import QuantLib as ql

try:
    from . import passiv_import_data
except ImportError:
    import passiv_import_data

def interpolate(x, data):
    keys = sorted(data.keys())
    for i in range(len(keys) - 1):
        if keys[i] <= x <= keys[i + 1]:
            x1, y1 = keys[i], data[keys[i]]
            x2, y2 = keys[i + 1], data[keys[i + 1]]
            y = y1 + (x - x1) * (y2 - y1) / (x2 - x1)
            return y
    return None  # x is out of the range of the data

# def marktwert(cpn,yld,rlz,tilgung):
#     if yld==0:
#         yld=0.0000001
#     yld = yld/100
#     preis = cpn/yld+(tilgung-cpn/yld)*(1+yld)**(-rlz)
#     return preis

# def marktwert_neu(cpn,yld,rlz,tilgung, tage_in_zukunft):
#     rlz = rlz - tage_in_zukunft/365
#     yld = yld/100
#     preis = cpn/yld+(tilgung-cpn/yld)*(1+yld)**(-rlz)
#     return preis



# Methoden zur Restlaufzeit Berechnung - Ende
def get_year_fraction_anniversary_old(start_date, end_date):
    """
    Urspruengliche Anniversary-Methode:
    Ganze Kalenderjahre + Resttage / Tage des exakten Folgejahres.
    """
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    years = end.year - start.year
    anniversary = start.replace(year=end.year)
    if anniversary > end:
        years -= 1
        prev_anniversary = start.replace(year=end.year - 1)
        next_anniversary = anniversary
    else:
        prev_anniversary = anniversary
        next_anniversary = start.replace(year=end.year + 1)

    remaining_days = (end - prev_anniversary).days
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
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)

    freq_int = int(freq)
    if freq_int <= 0:
        raise ValueError("freq muss > 0 sein.")
    if 12 % freq_int != 0:
        raise ValueError("freq muss ein Teiler von 12 sein, z. B. 1, 2, 3, 4, 6 oder 12.")

    if end <= start:
        return 0.0 if end == start else -get_year_fraction_anniversary(end, start, freq=freq_int)

    period_months = 12 // freq_int
    current_period_start = start
    completed_periods = 0

    while True:
        next_period_start = current_period_start + pd.DateOffset(months=period_months)
        if next_period_start <= end:
            completed_periods += 1
            current_period_start = next_period_start
        else:
            break

    next_period_start = current_period_start + pd.DateOffset(months=period_months)
    remaining_days = (end - current_period_start).days
    days_in_period = (next_period_start - current_period_start).days

    return completed_periods / freq_int + (remaining_days / days_in_period) / freq_int





def get_year_fraction_bloomberg(start_date, end_date):
    """
    Methode 2: Bloomberg / Act/365.25 Standard (Gesamte Tage / 365.25).
    Vorteil: Einfach, schnell und von Bloomberg-Terminals für YTM/Duration verwendet.
    """
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    days = (end - start).days
    return days / 365.25

def get_year_fraction_exact(start_date, end_date, method='bloomberg', freq=1):
    """
    Grundfunktion zur Berechnung der Restlaufzeit (Year Fraction).
    
    Parameters:
      - start_date : Start- bzw. Settlement-Datum
      - end_date   : Fälligkeitsdatum (Maturity)
            - method     : 'anniversary', 'anniversary_old', 'bloomberg' oder 'isda'
            - freq       : Kuponfrequenz pro Jahr fuer anniversary, z. B. 1, 2, 4, 12
    """
    method_lower = str(method).lower()
    if method_lower in ['anniversary', 'method1', 'm1']:
        return get_year_fraction_anniversary(start_date, end_date, freq=freq)
    elif method_lower in ['anniversary_old', 'method1_old', 'm1_old']:
        return get_year_fraction_anniversary_old(start_date, end_date)
    elif method_lower in ['bloomberg', 'method2', 'm2']:
        return get_year_fraction_bloomberg(start_date, end_date)
    elif method_lower == 'isda':
        # Convert to pandas datetime first
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        
        # Convert to QuantLib Date objects
        d1 = ql.Date(start_dt.day, start_dt.month, start_dt.year)
        d2 = ql.Date(end_dt.day, end_dt.month, end_dt.year)
        
        # Use ActualActual with ISDA convention
        return ql.ActualActual(ql.ActualActual.ISDA).yearFraction(d1, d2, d1, d2)
    else:
        raise ValueError(f"Unbekannte Methode: {method}")
# Methoden zur Restlaufzeit Berechnung - Ende






# Feiertage für Kuponzahlungen oder Tilgungen - Anfang
def get_easter_holidays(year: int, verbose=False) -> dict[str, date]:
    """Gibt Karfreitag und Ostermontag für ein gegebenes Jahr zurück.

    Nutzt die `holidays`-Library, falls verfügbar,
    sonst den anonymen Gauß-Algorithmus.
    """
    try:
        import holidays as hol
        de = hol.Germany(years=year)
        karfreitag  = next(d for d, name in de.items() if 'Karfreitag' in name or 'Good Friday' in name)
        ostermontag = next(d for d, name in de.items() if 'Ostermontag' in name or 'Easter Monday' in name)
    except (ImportError, StopIteration):
        # Gauß-Algorithmus für Ostersonntag        
        a = year % 19
        b = year % 4
        c = year % 7
        d = (19 * a + 24) % 30
        e = (2 * b + 4 * c + 6 * d + 5) % 7
        ostersonntag = date(year, 3, 22) + timedelta(days=d + e)
        if d == 29 and e == 6:
                ostersonntag -= timedelta(days=7)
        elif d == 28 and e == 6 and a > 10:
                ostersonntag -= timedelta(days=7)
        karfreitag  = ostersonntag - timedelta(days=2)
        ostermontag = ostersonntag + timedelta(days=1)
    return {'Karfreitag': karfreitag, 'Ostermontag': ostermontag}

def target2_holidays(year: int, verbose=False) -> dict[str, date]:
    """Gibt die TARGET2-Feiertage für ein gegebenes Jahr zurück.

    Nutzt die `holidays`-Library, falls verfügbar,
    sonst den anonymen Gauß-Algorithmus.
    """
    try:
        import holidays as hol
        if verbose:
            print(f"Using holidays library to get TARGET2 holidays for {year}.")
        target2 = hol.EuropeanCentralBank(years=year)
        target2_holidays = {d: name for d, name in target2.items()}

    except ImportError:
        if verbose:
            print(f"holidays library not available. Using gauss formula for {year}.") 
        # Wenn holidays nicht verfügbar ist, geben wir eine leere Liste zurück
        target2_holidays = get_easter_holidays(year, verbose=verbose)
        target2_holidays = {v: k for k, v in get_easter_holidays(year).items()}
        target2_holidays.update({
            date(year, 1, 1): "New Year's Day",
            date(year, 5, 1): "1 May (Labour Day)",
            date(year, 12, 25): "Christmas Day",
            date(year, 12, 26): "26 December",
        })
    return target2_holidays
# Feiertage für Kuponzahlungen oder Tilgungen - Ende



def calculate_bond_values(tilgung=100, coupon=5, ytm=5, rlz=2.8, freq=1):
    """
    Calculates Macaulay and Modified Duration as well as Clean & Dirty prices for integer and fractional maturities.
    
    tilgung / face_value : Par value (default 100)
    coupon_rate          : Annual coupon rate (percentage e.g. 0.5 for 0.5% or decimal 0.005)
    ytm                  : Annual Yield to Maturity (percentage e.g. 3.021117 for 3.02% or decimal 0.0302)
    rlz                  : Years to maturity (e.g. 5.961643)
    freq                 : Coupon payments per year (1 for annual, 2 for semi-annual)
    """
        
    # Convert percentage inputs to decimal
    # If either input is passed as percentage (> 1, e.g. ytm=3.02), treat both as percentages
    coupon = coupon / 100.0
    if ytm == 0:
        ytm = 0.0000001  # Avoid division by zero
    ytm = ytm / 100.0

    if rlz <= 0:
        rlz = 0.0000001  # Avoid division by zero
    
    period_len = 1.0 / freq
    first_payment_time = rlz % period_len

    # Snap near coupon boundaries to avoid numerical artifacts in accrued interest.
    # Example: rlz=27.0001 (de-facto coupon date) should not create almost full accrual.
    one_hour = 1.0 / (365.25 * 24.0)
    if first_payment_time < one_hour or abs(period_len - first_payment_time) < one_hour:
        first_payment_time = period_len
        
    num_payments = math.ceil(rlz * freq)
    payment_times = [first_payment_time + i * period_len for i in range(num_payments)]
    
    coupon_pmt = (coupon * tilgung) / freq
    y_per_period = ytm / freq
    
    dirty_price = 0
    weighted_pv = 0
    
    for t in payment_times:
        is_final = (t == payment_times[-1])
        cf = (coupon_pmt + tilgung) if is_final else coupon_pmt
        
        # Discount factor for exact time t in years
        pv_cf = cf / ((1 + ytm) ** t)
        
        dirty_price += pv_cf
        weighted_pv += t * pv_cf
        
    mac_duration = weighted_pv / dirty_price
    mod_duration = mac_duration / (1 + y_per_period)
    
    # Calculate accrued interest (Stückzinsen) for fractional coupon period
    elapsed_fraction = (period_len - first_payment_time) / period_len
    accrued_interest = coupon_pmt * elapsed_fraction
    clean_price = dirty_price - accrued_interest
    
    return {
            "price_theo": round(clean_price, 6),
            "dirty_theo": round(dirty_price, 6),
            "accr_int": round(accrued_interest, 6),
            "mac_dur": round(mac_duration, 6),
            "mod_dur": round(mod_duration, 6)
        }


def calculate_bond_values_quantlib(tilgung=100, coupon=5, ytm=5, rlz=2.8, freq=1):
    """
    QuantLib-based valuation with the same output format as calculate_bond_values().

    Notes:
    - Input rates are expected in percent (e.g. coupon=1.8, ytm=3.6).
    - Uses a time-based cashflow grid derived from rlz/freq and QuantLib discounting.
    - Returns clean price, dirty price, accrued interest, Macaulay and Modified duration.
    """

    coupon = coupon / 100.0
    if ytm == 0:
        ytm = 0.0000001
    ytm = ytm / 100.0

    if rlz <= 0:
        rlz = 0.0000001

    freq = max(1, int(freq))
    period_len = 1.0 / freq
    first_payment_time = rlz % period_len

    # Keep coupon-boundary snapping consistent with calculate_bond_values.
    one_hour = 1.0 / (365.25 * 24.0)
    if first_payment_time < one_hour or abs(period_len - first_payment_time) < one_hour:
        first_payment_time = period_len

    num_payments = math.ceil(rlz * freq)
    payment_times = [first_payment_time + i * period_len for i in range(num_payments)]

    coupon_pmt = (coupon * tilgung) / freq
    y_per_period = ytm / freq

    # QuantLib interest-rate object for discounting cashflows at exact time points.
    ql_rate = ql.InterestRate(ytm, ql.Actual365Fixed(), ql.Compounded, ql.Annual)

    dirty_price = 0.0
    weighted_pv = 0.0
    for t in payment_times:
        is_final = (t == payment_times[-1])
        cf = (coupon_pmt + tilgung) if is_final else coupon_pmt
        pv_cf = cf * ql_rate.discountFactor(t)
        dirty_price += pv_cf
        weighted_pv += t * pv_cf

    mac_duration = weighted_pv / dirty_price
    mod_duration = mac_duration / (1 + y_per_period)

    elapsed_fraction = (period_len - first_payment_time) / period_len
    accrued_interest = coupon_pmt * elapsed_fraction
    clean_price = dirty_price - accrued_interest

    return {
            "price_theo": round(clean_price, 6),
            "dirty_theo": round(dirty_price, 6),
            "accr_int": round(accrued_interest, 6),
            "mac_dur": round(mac_duration, 6),
            "mod_dur": round(mod_duration, 6)
        }



# def calc_prices(df, change, tage_in_zukunft, euro_basis=10_000_000):
#     df = df.copy()
#     df['weight_intern'] = df['weight'].mul(100)/df['weight'].sum()
#     df['diff'] = df['rlz'].apply(lambda x: interpolate(x, change))
#     df['diff'] = np.where(df['bond_description']=='Cash',0,df['diff'])
#     df['yield_new'] = df['yield'] + df['diff']
#     df['rlz_new'] = df.apply()
#     df['price_theo'] = df.apply(lambda row: calculate_bond_values(tilgung=100, coupon=row['coupon'], ytm=row['yield_new'], rlz=row['rlz'], freq=row['freq'])['price_theo'], axis=1)
#     # df['price_theo_new'] = df.apply(lambda row: marktwert_neu(cpn=row['coupon'],yld= row['yield_new'],rlz= row['rlz'],tilgung= 100, tage_in_zukunft=tage_in_zukunft), axis=1)
#     df['dirty'] = df['price_theo']+df['accr_int']
#     df['dirty_new'] = df['price_theo_new'] + df['accr_int'] + df['coupon'].div(365).mul(tage_in_zukunft)
#     df['change'] = df['dirty_new']/df['dirty']
#     df['wert'] = df['weight_intern']*euro_basis/100
#     df['wert_new'] = df['weight_intern']*df['change']*euro_basis/100
#     gesamtgewicht = df['weight'].sum()
    
#     return gesamtgewicht, ((df['wert_new'].sum()/df['wert'].sum())-1)*100, df

# def calc_change_securites(df, change, tage_in_zukunft, extended = False):
#     df=df.copy()
#     df['yield_change'] = df['rlz'].apply(lambda x: interpolate(x, change))
#     df['yield_change'] = np.where(df['bond_description']=='Cash',0,df['yield_change'])
#     df['yield_old'] = df['yield'].copy()
#     df['yield_new'] = df['yield'] + df['yield_change']
#     df['yield_new'] = df['yield_new'].round(6)
#     df['yield_old'] = df['yield_old'].round(6)
#     df['price_theo_new'] = df.apply(lambda row: marktwert_neu(cpn=row['coupon'],
#                                                               yld= row['yield_new'],
#                                                               rlz= row['rlz'],tilgung= 100, 
#                                                               tage_in_zukunft=tage_in_zukunft), axis=1)
#     df['dirty_old'] = df['price_theo']+df['accr_int']
#     df['dirty_new'] = df['price_theo_new'] + df['accr_int'] + df['coupon'].div(365).mul(tage_in_zukunft)
#     df['change_factor'] = df['dirty_new']/df['dirty_old']

#     if extended:
#         df = df[['isin','change_factor','dirty_old','dirty_new','yield_old','yield_new','yield_change']].reset_index(drop=True)
#     else:
#         df = df[['isin','change_factor']].reset_index(drop=True)
#     return df

def krates_colnames(krates:list):
    krd_spaltennamen = ['krd' + (f'0{item}' if item < 10 else str(item)) for item in krates]
    return krd_spaltennamen

# Kennzahlen
def krd_summe(df):
    krd_spaltennamen= [item for item in df.columns.to_list() if 'krd' in item]
    k = df[krd_spaltennamen].to_numpy()
    w = df['weight'].to_numpy()
    return np.dot(k.T,w) /100

def krd_diff(df1,df2):
    d1 = krd_summe(df1)
    d2 = krd_summe(df2)
    return d1-d2

def rendite(df, runden=2):
    df = df.copy()
    yld = df['yield'].to_numpy()
    w = df['weight'].to_numpy()
    return round(np.dot(yld.T, w)/100,runden)

def rlz(df,runden=2):
    yld = df['rlz'].to_numpy()
    w = df['weight'].to_numpy()
    return round(np.dot(yld.T, w)/100,runden)

def duration(df,runden=2):
    df = df.copy()
    dur = df['mac_dur'].to_numpy()
    w = df['weight'].to_numpy()
    return round(np.dot(dur.T, w)/100,runden)

def coupon(df,runden=2):
    df = df.copy()
    dur = df['coupon'].to_numpy()
    w = df['weight'].to_numpy()
    return round(np.dot(dur.T, w)/100,runden)

def convexity(df,runden=2):
    df = df.copy()
    dur = df['convexity'].to_numpy()
    w = df['weight'].to_numpy()
    return round(np.dot(dur.T, w)/100,runden)

def krd_table_diff(fonds, bm, krates:list, addSums:bool=True, runden:int = 2):
    """fonds, bm, krates, addSums, runden
    """


    fonds = fonds.copy()
    bm = bm.copy()
    krd_spaltennamen= [item for item in fonds.columns.to_list() if 'krd' in item]
    if krd_spaltennamen != []:
        fonds = fonds.drop(krd_spaltennamen, axis=1)
    krd_spaltennamen= [item for item in bm.columns.to_list() if 'krd' in item]
    if krd_spaltennamen != []:
        bm = bm.drop(krd_spaltennamen, axis=1)
    krd_spaltennamen = ['krd' + (f'0{item}' if item < 10 else str(item)) for item in krates]
    
    fonds[krd_spaltennamen] = fonds.apply(lambda row: passiv_import_data.keydur3(ttm=row['rlz'],
                                        coupon=row['coupon'],
                                        yld=row['yield'],
                                        frq=row['freq'],
                                        dur_target=row['mac_dur'],
                                        krates=krates), axis=1, result_type='expand')
    bm[krd_spaltennamen] = bm.apply(lambda row: passiv_import_data.keydur3(ttm=row['rlz'],
                                            coupon=row['coupon'],
                                            yld=row['yield'],
                                            frq=row['freq'],
                                            dur_target=row['mac_dur'],
                                            krates=krates), axis=1, result_type='expand')


    result = pd.DataFrame()
    #krd_spaltennamen= [item for item in bm.columns.to_list() if 'krd' in item]
    laender = bm['country'].drop_duplicates().to_list() + fonds['country'].drop_duplicates().to_list()
    laender = sorted(set(laender))
    for land in laender:
        pf_land=fonds.query("country == @land").reset_index(drop=True)
        bm_land=bm.query("country == @land").reset_index(drop=True)
        d = krd_diff(pf_land, bm_land)
        d = pd.DataFrame(list(d), columns=[land]).T
        result = pd.concat([result, d])

    result.columns = krd_spaltennamen

    result['country'] = result.index
    result=result[['country']+krd_spaltennamen].reset_index(drop=True)
    
    if addSums:
        result['sSumme'] = result[krd_spaltennamen].sum(axis=1)
        
        zSumme = pd.DataFrame(krd_diff(fonds, bm)).T
        zSumme.columns = krd_spaltennamen
        zSumme['country'] = 'zSumme'
        zSumme['sSumme'] = result['sSumme'].sum().round(runden)
        result = pd.concat([result, zSumme], ignore_index=True)
        result[krd_spaltennamen + ['sSumme']] = result[krd_spaltennamen +['sSumme']].astype('float64').round(runden)
    else:
        result[krd_spaltennamen] = result[krd_spaltennamen].astype('float64').round(runden)

    return result

def krd_table_abs(df, krates, addSums=True, runden = 2):
    result = pd.DataFrame()
    krd_spaltennamen= [item for item in df.columns.to_list() if 'krd' in item]
    if krd_spaltennamen != []:
        df = df.drop(krd_spaltennamen, axis=1)
    krd_spaltennamen = ['krd' + (f'0{item}' if item < 10 else str(item)) for item in krates]
    df[krd_spaltennamen] = df.apply(lambda row: passiv_import_data.keydur3(ttm=row['rlz'],
                                        coupon=row['coupon'],
                                        yld=row['yield'],
                                        frq=row['freq'],
                                        dur_target=row['mac_dur'],
                                        krates=krates), axis=1, result_type='expand')

    laender = df['country'].drop_duplicates().to_list()
    laender.sort()
    for land in laender:
        pf_land=df.query("country == @land").reset_index(drop=True)
        d = krd_summe(pf_land)
        d = pd.DataFrame(list(d), columns=[land]).T
        result = pd.concat([result, d])

    result.columns = krd_spaltennamen

    result['country'] = result.index
    result=result[['country']+krd_spaltennamen].reset_index(drop=True)
    
    if addSums:
        result['sSumme'] = result[krd_spaltennamen].sum(axis=1)
        
        zSumme = pd.DataFrame(result[krd_spaltennamen].sum(axis=0)).T
        zSumme.columns = krd_spaltennamen
        zSumme['country'] = 'zSumme'
        zSumme['sSumme'] = result['sSumme'].sum().round(runden)
        result = pd.concat([result, zSumme], ignore_index=True)
        result[krd_spaltennamen + ['sSumme']] = result[krd_spaltennamen +['sSumme']].astype('float64').round(runden)
    else:
        result[krd_spaltennamen] = result[krd_spaltennamen].astype('float64').round(runden)

    return result

def country_table_abs(df, runden=2):
    country = df.groupby('country').agg({'weight':'sum'}).reset_index()
    country['weight'] = country['weight'].astype('float64').round(runden)
    return country

def country_table_diff(fonds_df, bm_df, runden=2):
    fonds_df = fonds_df.copy()
    bm_df = bm_df.copy()
    country_bm = country_table_abs(bm_df, runden=runden).rename(columns={'weight':'weight_bm'})
    country_fonds = country_table_abs(fonds_df, runden=runden).rename(columns={'weight':'weight_fonds'})
    ges = country_fonds.merge(country_bm, how='outer', on='country')
    ges[['weight_bm','weight_fonds']]=    ges[['weight_bm','weight_fonds']].fillna(0)
    ges['weight'] = ges['weight_fonds'] - ges['weight_bm']
    ges = ges.drop(['weight_fonds','weight_bm'],axis=1)
    ges['weight'] = ges['weight'].round(runden)
    return ges 

def calcPreviewWeightswithBMDate(bm, pv):
    """bm ... df benchmark
       pv ... df preview
       Berechnet die Preview Daten mit Daten der Benchmark
       soweit vorhanden"""

    def c_n_w(bm, pv):
        #calculate new weights (only)
        def renameBMcolumn(df, cols: list, prefix='bm'):
            for col in cols:
                df[f'bm_{col}'] = df[col].copy()
            return df

        bm = bm.copy()
        bm = renameBMcolumn(bm, cols=['price','accr_int'])
        new_weights = pv[['isin','price','accr_int','weight']].merge(bm[['isin','bm_price','bm_accr_int']], on='isin', how='left')
        new_weights['bm_price'] = new_weights['bm_price'].fillna(new_weights['price'])
        new_weights['bm_accr_int'] = new_weights['bm_accr_int'].fillna(new_weights['accr_int'])
        new_weights['factor'] = (new_weights['bm_price']+new_weights['bm_accr_int'])/(new_weights['price']+new_weights['accr_int'])
        new_weights['nweight'] = new_weights['weight'].mul(new_weights['factor'])
        new_weights['nweight'] = new_weights['nweight'].mul(100).div(new_weights['nweight'].sum())
        new_weights = new_weights[['isin','weight']].rename(columns={'nweight':'weight'}).reset_index(drop=True)
        return new_weights

    bm = bm.copy()
    bm_isins = bm['isin'].to_list()
    pv_isins = bm['isin'].to_list()
    col_order = pv.columns.to_list()
    new_in_pv = pv.query("isin not in @bm_isins").drop('weight', axis=1).reset_index(drop=True)
    old_in_pv = pv.query("isin in @bm_isins").reset_index(drop=True)    
    new = (old_in_pv[['isin','mat_sect','outs_loc_mm','source']]
                    .merge(bm.drop(['weight','mat_sect','outs_loc_mm','source'], axis=1), on='isin', how='left'))
    new = pd.concat([new_in_pv,new], ignore_index=True).merge(c_n_w(bm, pv), on='isin', how='left')[col_order].sort_values(['country','rlz']).reset_index(drop=True)
    return new

def zeichne_land_passiv(df, land=None, szenario = None, titel = None, rlz_limit = [], exclude_cash = True, dimension = [16,9]):
    if exclude_cash:
        df = df.query("not isin.str.contains('CASH')").reset_index(drop=True)
    if land!=None:
        df = df.query("country==@land").reset_index(drop=True)
    if szenario!=None:
        df = df.query("scenario==@szenario").reset_index(drop=True)
    if len(rlz_limit)==0:
        maximum = math.ceil(df['rlz'].max())
        minimum = math.floor(df['rlz'].min())
        
    p= (p9.ggplot(df)
        +p9.geom_point(p9.aes(x='rlz',y='yield',group='source', size='weight'), color='darkblue')
        +p9.geom_point(p9.aes(x='rlz',y='yield_new',group='source', size='weight'), color='blue')
        +p9.geom_line(p9.aes(x='rlz',y='yield',group='source'), color='darkblue',linetype='dotted')
        +p9.geom_line(p9.aes(x='rlz',y='yield_new',group='source'), color='blue',linetype='dotted')
        +p9.scale_x_continuous(limits=[minimum,maximum], breaks=range(0,106,2))
        +p9.facet_grid('source~')
        +p9.theme_bw()
        +p9.theme(legend_position='bottom',
                legend_title=p9.element_blank(),
                legend_key=p9.element_blank(),
                legend_text=p9.element_text(family='Amalia', size=12))
        +p9.theme(figure_size=dimension)
        +p9.theme(strip_text=p9.element_text(size=16, family='Amalia'))
        +p9.theme(plot_background=p9.element_rect(fill='white'))
        +p9.theme(axis_text_y=p9.element_text(size=15, family='Amalia'))
        +p9.theme(axis_text_x=p9.element_text(size=9, family='Amalia'))
        +p9.theme(axis_title_x=p9.element_text(size=15, family='Amalia'))    
        +p9.theme(axis_title_y=p9.element_text(size=15, family='Amalia'))    
        +p9.theme(plot_title=p9.element_text(size=17, family='Amalia'))
        )
    if titel!= None:
        p=p+ (
            p9.labs(x='Tenor',y='Yield', title=titel)
        )
    else:
        p=p+ (
            p9.labs(x='Tenor',y='Yield')
        )
    return p

def zeichne_vergleich_land_passiv(df1, df2, df1_name = 'bm', df2_name='fund', x_achse = 'rlz',
                           land=None, szenario = None, titel = None, x_limits = [], exclude_cash = True, dimension = [16,9],
                           multiwindow = False):
    df1 = df1.copy()
    df2 = df2.copy()
    x_achse = x_achse.lower()

    farben = ['#4E79A7',
            '#A0CBE8',
            '#F28E2B',
            '#FFBE7D',
            '#59A14F',
            '#8CD17D',
            '#B6992D',
            '#F1CE63',
            '#499894',
            '#86BCB6',
            '#E15759',
            '#FF9D9A',
            '#79706E',
            '#BAB0AC',
            '#D37295',
            '#FABFD2',
            '#B07AA1',
            '#D4A6C8',
            '#9D7660',
            '#D7B5A6']

    df1['source'] = df1_name
    df2['source'] = df2_name
    df1['weight'] = df1['weight'].astype('float32')
    df2['weight'] = df2['weight'].astype('float32')
    df = pd.concat([df1, df2], ignore_index=True)
 
    if exclude_cash:
        df = df.query("not isin.str.contains('CASH', case=False)").reset_index(drop=True)
    
    if land!=None:
        df = df.query("country==@land").reset_index(drop=True)
    if szenario!=None:
        df = df.query("scenario==@szenario").reset_index(drop=True)
        
  
    if (x_achse == 'duration') or (x_achse=='dur') or (x_achse=='d'):
        df['x_achse'] = df['mac_dur']
        x_achse_text = 'Duration'
    else:
        df['x_achse'] = df['rlz']
        x_achse_text = 'Tenor'

    if len(x_limits)==0:
        maximum = math.ceil(df['x_achse'].max())
        minimum = math.floor(df['x_achse'].min())

 
    p= (
        p9.ggplot(df)
    +p9.geom_point(p9.aes(x='x_achse',y='yield',group='country', size='weight', color='country'))
    +p9.geom_line(p9.aes(x='x_achse',y='yield',group='country', color='country'),linetype='dotted')

    +p9.scale_color_manual(values=farben)

    +p9.theme_bw()
    +p9.theme(legend_position='bottom',
            legend_title=p9.element_blank(),
            legend_key=p9.element_blank(),
            legend_text=p9.element_text(family='Amalia', size=9))
    +p9.theme(figure_size=dimension)
    +p9.theme(strip_text=p9.element_text(size=16, family='Amalia'))
    +p9.theme(plot_background=p9.element_rect(fill='white'))
    +p9.theme(axis_text_y=p9.element_text(size=15, family='Amalia'))
    +p9.theme(axis_text_x=p9.element_text(size=12, family='Amalia'))
    +p9.theme(axis_title_x=p9.element_text(size=15, family='Amalia'))    
    +p9.theme(axis_title_y=p9.element_text(size=15, family='Amalia'))    
    +p9.theme(plot_title=p9.element_text(size=17, family='Amalia'))
    +p9.guides(size = p9.guide_legend(nrow = 1))


    )

    if multiwindow:
        p=p+(p9.facet_grid('source~country'))
        p=p+(p9.scale_x_continuous(limits=[minimum,maximum], breaks=range(0,106,10)))
        p=p+(p9.guides(color='none'))

    else:
        p=p+(p9.facet_grid('source~'))
        p=p+(p9.scale_x_continuous(limits=[minimum,maximum], breaks=range(0,106,2)))
        p=p+(p9.guides(color='none'))

    if titel!= None:
        p=p+ (
            p9.labs(x=x_achse_text,y='Yield', title=titel)
        )
    else:
        p=p+ (
            p9.labs(x=x_achse_text,y='Yield')
        )


    return p



#def fondsExistsold(notebook_dir, datum, pfad):
    #'./secor/'
    pfad = Path(notebook_dir,pfad)
    found = True
    dateiname = Path(pfad,datum,'bm_fix.parquet')
    
    if not os.path.isfile(dateiname):
        found = False
        print(dateiname)
    dateiname = Path(pfad,datum,'bm_res.parquet')   
    if not os.path.isfile(dateiname):
        found = False
    
    return found

def fondsExists(verzeichnis):
    #'./secor/'
    found = True
    dateiname = Path(verzeichnis,'bm_fix.parquet')
    if not os.path.isfile(dateiname):
        found = False
    dateiname = Path(verzeichnis,'bm_res.parquet')   
    if not os.path.isfile(dateiname):
        found = False
   
    return found

#def readBenchmark_fix_res_old(notebook_dir, datum, pfad=None):
    # "returns Benchmark (whole), Benchmark (fixed part), Benchmark (variable part)"

    # if fondsExists(datum=datum, pfad=pfad, notebook_dir=notebook_dir):
    #     pfad = Path(notebook_dir, pfad, datum)
    #     bm_fix = pd.read_parquet(Path(pfad,'bm_fix.parquet'))
    #     bm_res = pd.read_parquet(Path(pfad,'bm_res.parquet'))
    #     bm = pd.concat([bm_fix, bm_res], ignore_index=True)
    # else:
    #     bm = passiv_import_data.import_data(datum=datum)
    #     bm_fix = None
    #     bm_res = None
    # return bm, bm_fix, bm_res

def readBenchmark_fix_res(verzeichnis):
    "returns Benchmark (whole), Benchmark (fixed part), Benchmark (variable part)"

    if fondsExists(verzeichnis):
        bm_fix = pd.read_parquet(Path(verzeichnis,'bm_fix.parquet'))
        bm_res = pd.read_parquet(Path(verzeichnis,'bm_res.parquet'))
        bm = pd.concat([bm_fix, bm_res], ignore_index=True)
        return bm, bm_fix, bm_res
    return False


#def readOptimizedFundold(notebook_dir, pfad, datum, fonds_fix=pd.DataFrame(), verbose=False):
    # verzeichnis = Path(notebook_dir,pfad,datum)
    # dateien = os.listdir(verzeichnis)
    # dateien = [datei for datei in dateien if datum in datei]
    # fonds = pd.DataFrame()
    # for datei in dateien:
    #     temp = pd.read_parquet(Path(verzeichnis,datei))
    #     fonds = pd.concat([fonds,temp], ignore_index=True)
    # if fonds_fix.shape[0]>0:
    #     fonds = pd.concat([fonds, fonds_fix], ignore_index=True)
    #     bond_info = fonds.groupby('isin').nth(0).drop('weight', axis=1).reset_index(drop=True)
    #     fonds_weights = fonds.groupby('isin').agg({'weight':'sum'})
    #     fonds = fonds_weights.merge(bond_info, how='left', on='isin')  
    # fonds = fonds.sort_values(['country', 'rlz','isin']).reset_index(drop=True)
    # if verbose:
    #     print(f"Gesamtgewicht: {fonds['weight'].sum()}")
    #     print(f"Anzahl: {fonds['isin'].count()}")
    #     print(f"{fonds.groupby('country').agg({'weight':'sum','isin':'count'}).reset_index()}")
    # return fonds

def fundIncludingBMBonds(fonds, bm):
    """kombiniert einen fonds mit den bonds einer benchmark,
    die gewichte der fehlenden BM Bonds sind dann 0"""

    fonds = fonds.copy()
    bm = bm.copy()
    fonds_cols = fonds.columns.to_list()
    bm_cols = bm.columns.to_list()
    cols = [item for item in fonds_cols if item in bm_cols]
    fonds_isins = fonds['isin'].to_list()
    bm_isins = bm['isin'].to_list()
    missing_isin = [item for item in bm_isins if item not in fonds_isins]
    missing = bm.query("isin in @missing_isin").reset_index(drop=True)
    missing['weight']=0
    gesamt = pd.concat([fonds, missing], ignore_index=True).sort_values(['country','rlz']).reset_index(drop=True)
    return gesamt


def readOptimizedFund(verzeichnis, fonds_fix=pd.DataFrame(), verbose=False):
    dateien = os.listdir(verzeichnis)
    dateien = [datei for datei in dateien if 'country' in datei]
    fonds = pd.DataFrame()
    for datei in dateien:
        temp = pd.read_parquet(Path(verzeichnis,datei))
        fonds = pd.concat([fonds,temp], ignore_index=True)
    if fonds_fix.shape[0]>0:
        fonds = pd.concat([fonds, fonds_fix], ignore_index=True)
        bond_info = fonds.groupby('isin').nth(0).drop('weight', axis=1).reset_index(drop=True)
        fonds_weights = fonds.groupby('isin').agg({'weight':'sum'})
        fonds = fonds_weights.merge(bond_info, how='left', on='isin')  
    fonds = fonds.sort_values(['country', 'rlz','isin']).reset_index(drop=True)
    if verbose:
        print(f"Gesamtgewicht: {fonds['weight'].sum()}")
        print(f"Anzahl: {fonds['isin'].count()}")
        print(f"{fonds.groupby('country').agg({'weight':'sum','isin':'count'}).reset_index()}")
    return fonds


#def saveCompleteFundold(notebook_dir, customer_path, datum, verbose=True, save=False):
    # "returns the Benchmark and the consolidated Fund"
    # bm, bm_fix, bm_res = readBenchmark_fix_res(notebook_dir=notebook_dir,datum=datum, pfad=customer_path)
    # fonds = readOptimizedFund(notebook_dir = notebook_dir, datum=datum, pfad=customer_path, fonds_fix=bm_fix, verbose=False)
    # fonds_ohnecash=fonds.query("not isin.str.contains('CASH', case=False)").reset_index(drop=True)
    # laender = fonds['country'].drop_duplicates().to_list()
    
    # if verbose:
    #     print("BM:",bm['weight'].sum())
    #     print("Fonds:",fonds['weight'].sum())

    # bm_summary = bm.groupby('isin').nth(0).groupby('country').agg({'weight':'sum','isin':'count'}).reset_index().rename(columns={'weight':'bm_weight', 'isin':'bm_isin'})
    # fonds_summary = fonds.groupby('isin').nth(0).query("not isin.str.contains('CASH', case=False)").groupby('country').agg({'weight':'sum','isin':'count'}).reset_index().rename(columns={'weight':'pf_weight', 'isin':'pf_isin'})
    # summary = fonds_summary.merge(bm_summary, on='country', how='left')[['country','pf_weight','bm_weight','pf_isin','bm_isin']]
    # summary['pct'] = summary['pf_isin'].div(summary['bm_isin']).mul(100).round(0)
    
    # if verbose:
    #     print(summary)
    # print(f"Gesamt: {round(summary.pf_isin.sum()/summary.bm_isin.sum()*100)}%")
    # print(f"Gesamt: {summary.pf_isin.sum()}")
    # cash = fonds.query("isin.str.contains('CASH')").reset_index(drop=True)
    # if verbose:
    #     print(f"Cash: {cash['weight'].sum().round(1)}")
    # if save:
    #     bm.to_parquet(Path(notebook_dir,customer_path, datum,'bm.parquet'))
    #     fonds.to_parquet(Path(notebook_dir,customer_path, datum,'fonds.parquet'))
    #     cash.to_parquet(Path(notebook_dir,customer_path, datum,'cash.parquet'))
    #     fonds_ohnecash.to_parquet(Path(notebook_dir,customer_path, datum,'fonds_ohnecash.parquet'))
    #     if verbose:
    #         print("gespeichert")
    # return bm, fonds

def saveCompleteFund(verzeichnis, verbose=True, save=False):
    "returns the Benchmark and the consolidated Fund"
    bm, bm_fix, bm_res = readBenchmark_fix_res(verzeichnis=verzeichnis)
    fonds = readOptimizedFund(verzeichnis=verzeichnis, fonds_fix=bm_fix ,verbose=False)
    fonds_ohnecash=fonds.query("not isin.str.contains('CASH', case=False)").reset_index(drop=True)
    laender = fonds['country'].drop_duplicates().to_list()
    
    if verbose:
        print("BM:",bm['weight'].sum())
        print("Fonds:",fonds['weight'].sum())

    bm_summary = bm.groupby('isin').nth(0).groupby('country').agg({'weight':'sum','isin':'count'}).reset_index().rename(columns={'weight':'bm_weight', 'isin':'bm_isin'})
    fonds_summary = fonds.groupby('isin').nth(0).query("not isin.str.contains('CASH', case=False)").groupby('country').agg({'weight':'sum','isin':'count'}).reset_index().rename(columns={'weight':'pf_weight', 'isin':'pf_isin'})
    summary = fonds_summary.merge(bm_summary, on='country', how='left')[['country','pf_weight','bm_weight','pf_isin','bm_isin']]
    summary['pct'] = summary['pf_isin'].div(summary['bm_isin']).mul(100).round(0)
    
    if verbose:
        print(summary)
        print(f"Gesamt: {round(summary.pf_isin.sum()/summary.bm_isin.sum()*100)}%")
        print(f"Gesamt: {summary.pf_isin.sum()}")
    cash = fonds.query("isin.str.contains('CASH')").reset_index(drop=True)
    if verbose:
        print(f"Cash: {cash['weight'].sum().round(1)}")
    if save:
        bm.to_parquet(Path(verzeichnis,'bm.parquet'))
        fonds.to_parquet(Path(verzeichnis,'fonds.parquet'))
        cash.to_parquet(Path(verzeichnis,'cash.parquet'))
        fonds_ohnecash.to_parquet(Path(verzeichnis,'fonds_ohnecash.parquet'))
        if verbose:
            print("gespeichert")
    return bm, fonds



def exportBloomberg(fonds_or_bm, name, notebook_dir=None, datum=None, pfad=None):
    to_excel = fonds_or_bm.query("not isin.str.contains('CASH')").reset_index(drop=True)[['isin','weight']]
    to_excel['weight'] = to_excel['weight'].round(3)
    to_excel=to_excel.query("weight>.001").reset_index(drop=True)
    if (notebook_dir!=None) & (pfad!=None) & (datum!=None):
        dateiname = Path(notebook_dir, pfad, datum,  name)
    else:
        dateiname =name
    to_excel.to_excel(dateiname, index=False)
    return "ok"

def exportNominale(fonds, volume=100_000_000, runden = 10_000, bm = pd.DataFrame()):
    """Wandelt Gewichte in Nominale um
    fonds ... df, muss ['isin','weight','dirty_theo','country','rlz'] enthalten
    volume ... Wert in EUR
    runden ... auf wieviel soll Nominale gerundet werden
    bm ... optional, dann werden die fehlenden BM Bonds mit 0 Nominale hinzugenommen
    """
    fonds = fonds.copy()
    
    fonds = fonds.query("~isin.str.contains('CASH')").reset_index(drop=True)
    fonds = fonds[['isin','weight','dirty_theo','country','rlz']].reset_index(drop=True)
    fonds['nominale'] = (volume*fonds['weight'].div(fonds['dirty_theo']).div(runden)).round(0).mul(runden)
    fonds = fonds.drop(['weight','dirty_theo'], axis=1)
    if bm.shape[0]>0:
        bm = bm.copy()
        bm = bm[['isin','country','rlz']]
        missing = bm[~bm['isin'].isin(fonds['isin'])].reset_index(drop=True)
        missing['nominale'] = 0
        fonds = pd.concat([fonds, missing], ignore_index=True)
    fonds = fonds.sort_values(['country','rlz']).reset_index(drop=True)
    fonds=fonds.drop(['country','rlz'], axis=1)
    return fonds

def compareFunds(new, old, threshold = .02, verbose=True):
    """
    new
    old
    
    """
    df1 = new.copy()
    df2 = old.copy()
    df1 = df1.rename(columns={'weight':'w_new','outs_loc_mm':'outs_loc_mm_new'})
    df2 = df2.rename(columns={'weight':'w_old','outs_loc_mm':'outs_loc_mm_old'})
    df = df1[['isin','country','w_new','outs_loc_mm_new']].merge(df2[['isin','country','w_old','outs_loc_mm_old']], how='outer', on=['isin','country'])
    df = df.fillna(0)
    df['w_diff'] =df['w_new']-df['w_old']
    df['outs_loc_mm']=df['outs_loc_mm_new']-df['outs_loc_mm_old']
    df['outs_loc_mm'] = df['outs_loc_mm'].fillna(0)
    unterschied_w = df.query("w_diff.abs() > @threshold").query("w_new!=0").query("w_old!=0").reset_index(drop=True)
    unterschied_out = df.query("outs_loc_mm!=0").reset_index(drop=True)
    
    old_drop = df.query("w_new==0 & w_old>0").reset_index(drop=True)['isin'].to_list()
    old_drop = (df2.query("isin in @old_drop")
                   .rename(columns = {'w_old':'weight'})
                ).reset_index(drop=True)[['isin','bond_description','country','maturity','rlz','mac_dur','yield','weight']]
    
    new_add =  df.query("w_old==0 & w_new>0").reset_index(drop=True)['isin'].to_list()
    new_add = (df1.query("isin in @new_add")
                   .rename(columns = {'w_new':'weight'})
                ).reset_index(drop=True)[['isin','bond_description','country','maturity','rlz','mac_dur','yield','weight']]
    if verbose:
        print('Anzahl:')
        print(f'neu: {df1.shape[0]} alt: {df2.shape[0]}')
        print("Verschwindet:")
        od = old_drop[['isin','country','rlz','weight']].reset_index(drop=True)
        print(f'{od}')
        print(f"Verschwindet Summe:{od['weight'].sum():.2f}")
        print("---------------------------------------------------")
        print("kommt hinein:")
        na = new_add[['isin','country','rlz','weight']].reset_index(drop=True)
        print(f'{na}')
        print(f"Kommt rein Summe:{na['weight'].sum():.2f}")
        print("---------------------------------------------------")
        print("Grosse Änderungen Gewicht:")
        print(f'{unterschied_w}')  
        print("---------------------------------------------------")
        print("Änderungen Nominale:")
        print(f'{unterschied_out}')  
        print("---------------------------------------------------")
        print("Duration")
        print(f"neu: {duration(new):.2f} alt: {duration(old):.2f} diff: {(duration(new) - duration(old)):.2f}")
        print("---------------------------------------------------")
        print("Rendite")
        print(f"neu: {rendite(new):.2f} alt: {rendite(old):.2f} diff: {(rendite(new) - rendite(old)):.2f}")
        print("---------------------------------------------------")
    return old_drop, new_add, unterschied_w, unterschied_out

def overlapWeight(fonds, bm, runden=2):
    "Liefert die Differenzen [0] und die Übereinstimmung [1]"
    fonds = fonds.copy()
    bm = bm.copy()
    fonds = fonds[['isin','weight']].rename(columns={'weight':'w_f'})
    bm = bm[['isin','weight']].rename(columns={'weight':'w_b'})

    both = fonds.merge(bm, how='outer', on='isin')
    both['w_b'] = np.where(both['w_b'].isnull(),0, both['w_b'])
    both['w_f'] = np.where(both['w_f'].isnull(),0, both['w_f'])
    both['diff'] = (both['w_f']-both['w_b']).abs()
    both['same'] = both[['w_b', 'w_f']].min(axis=1)
    return round(both['diff'].sum(),runden), round(both['same'].sum(), runden)
    
def overlapSecurities(fonds, bm, runden=2):
    fonds = fonds.copy()
    bm = bm.copy()
    fonds = fonds[['isin','weight']].rename(columns={'weight':'w_f'})
    bm = bm[['isin','weight']].rename(columns={'weight':'w_b'})

    both = fonds.merge(bm, how='inner', on='isin')
    
    return round(both.shape[0]/bm.shape[0]*100,runden)

def rebaseWeights(df):
    df = df.copy()
    df['weight'] = df['weight']/df['weight'].sum()*100
    return df

def isGleicheKursbasis(df1, df2, name1='df1', name2='df2' ,verbose = True):
    ergebnis = False, pd.DataFrame(), 0
    price_name1 = name1 + '_price'
    price_name2 = name2 + '_price'
    
    df1 = df1.copy().rename(columns={'price':price_name1})
    df2 = df2.copy().rename(columns={'price':price_name2})
    both = df1[['isin',price_name1]].merge(df2[['isin',price_name2]], on='isin', how='inner')
    anz_ueberlappend = both.shape[0]
    if verbose:
        print(f'Überlappende Bonds: {anz_ueberlappend}')
    if anz_ueberlappend>0:
        gleich = both[both[price_name1] == both[price_name2]]
        anz_gleich = gleich.shape[0]
        if verbose:
            print(f'Gleicher Kurs: {anz_gleich} ({round((anz_gleich/anz_ueberlappend)*100,1)}%)')
        if anz_ueberlappend == anz_gleich:
            ergebnis=True, pd.DataFrame(), 100
        ungleich = both[both[price_name1] != both[price_name2]]
        ungleich = ungleich.reset_index(drop=True)
        if ungleich.shape[0]>0:
            ergebnis =False, ungleich, round((anz_gleich/anz_ueberlappend)*100,1)
    return ergebnis

def collect_coupon_payment_days_old(
    df: pd.DataFrame,
    maturity_col: str = "maturity",
    coupon_col: str = "coupon",
    isin_col: str = "isin",
    description_col: str = "bond_description",
    year: int | None = None,
    shift_past_coupon_day_to_next_year: bool = False,
    unique: bool = False,
):
    """
    DEPRECATED: Use collect_coupon_payment_days() instead for multi-frequency support.
    Extract coupon payment days from maturity dates (single payment per year).
    Coupon payment day is defined as the same day/month as maturity.

    Parameters:
    - year: year used to calculate weekday and payment date; defaults to current year.
        - shift_past_coupon_day_to_next_year: if True, a coupon payment date that already
            lies before today is moved to next year, but only if maturity is at/after that
            shifted date.

    Returns:
    - unique=True: sorted list like ['15-01', '23-04', ...]
    - unique=False: DataFrame with coupon day, weekday (for selected year),
      coupon date (for selected year), ISIN, description, and maturity
    """
    if maturity_col not in df.columns:
        raise KeyError(f"Column '{maturity_col}' not found in dataframe.")

    work = df.copy()

    # Keep coupon-paying bonds only, if a coupon column is available.
    if coupon_col in work.columns:
        coupon_num = pd.to_numeric(work[coupon_col], errors="coerce")
        work = work.loc[coupon_num > 0].copy()

    maturity_dates = pd.to_datetime(work[maturity_col], errors="coerce")
    target_year = pd.Timestamp.today().year if year is None else int(year)

    month = maturity_dates.dt.month
    day = maturity_dates.dt.day

    first_of_month = pd.to_datetime(
        {"year": target_year, "month": month, "day": 1},
        errors="coerce",
    )
    month_end_day = (first_of_month + pd.offsets.MonthEnd(1)).dt.day
    safe_day = np.minimum(day, month_end_day)

    coupon_date_for_year = pd.to_datetime(
        {"year": target_year, "month": month, "day": safe_day},
        errors="coerce",
    )

    if shift_past_coupon_day_to_next_year:
        today = pd.Timestamp.today().normalize()
        shifted_coupon_date = coupon_date_for_year + pd.DateOffset(years=1)
        can_shift = coupon_date_for_year.lt(today) & maturity_dates.ge(shifted_coupon_date)
        can_shift = can_shift.fillna(False)
        coupon_date_for_year = coupon_date_for_year.where(~can_shift, shifted_coupon_date)

    result = pd.DataFrame(
        {
            "coupon_payment_day": maturity_dates.dt.strftime("%d-%m"),
            "coupon_weekday": coupon_date_for_year.dt.day_name().str[:3].str.lower(),
            "coupon_payment_date_for_year": coupon_date_for_year,
            "coupon_year": coupon_date_for_year.dt.year,
            "isin": work[isin_col] if isin_col in work.columns else pd.NA,
            "bond_description": work[description_col] if description_col in work.columns else pd.NA,
            "maturity": maturity_dates,
            "country": work['country']
        }
    ).dropna(subset=["coupon_payment_day"])
    
    offset_days = result['coupon_weekday'].map({'sat': 2, 'sun': 3, 'mon': 4}).fillna(2)
    result['coupon_trade_day'] = result['coupon_payment_date_for_year'] - pd.to_timedelta(offset_days, unit='D')
    
    if unique:
        return sorted(result["coupon_payment_day"].unique().tolist())

    return result.sort_values(["coupon_payment_day", "isin"]).reset_index(drop=True)

def collect_coupon_payment_days(
    df: pd.DataFrame,
    maturity_col: str = "maturity",
    coupon_col: str = "coupon",
    isin_col: str = "isin",
    description_col: str = "bond_description",
    freq_col: str = "freq",
    year: int | None = None,
    shift_past_coupon_day_to_next_year: bool = False,
    unique: bool = False,
):
    """
    Extract coupon payment days from maturity dates, handling multiple coupon payments per year.
    
    If freq > 1, multiple coupon dates per year are calculated:
    - freq == 2: payments every 6 months
    - freq == 3: payments every 4 months
    - freq == 4: payments every 3 months (quarterly)
    - etc.

    Parameters:
    - year: year used to calculate weekday and payment date; defaults to current year.
    - shift_past_coupon_day_to_next_year: if True, a coupon payment date that already
        lies before today is moved to next year, but only if maturity is at/after that
        shifted date.
    - freq_col: column name for coupon frequency (1=annual, 2=semi-annual, 4=quarterly, etc.)

    Returns:
    - unique=True: sorted list like ['15-01', '23-04', ...]
    - unique=False: DataFrame with coupon day, weekday (for selected year),
      coupon date (for selected year), ISIN, description, maturity, frequency, and period
    """
    if maturity_col not in df.columns:
        raise KeyError(f"Column '{maturity_col}' not found in dataframe.")

    work = df.copy()

    # Keep coupon-paying bonds only, if a coupon column is available.
    if coupon_col in work.columns:
        coupon_num = pd.to_numeric(work[coupon_col], errors="coerce")
        work = work.loc[coupon_num > 0].copy()

    # Ensure freq column exists
    if freq_col not in work.columns:
        work[freq_col] = 1  # default to annual coupon

    # Reset index to avoid index alignment issues after filtering
    work = work.reset_index(drop=True)
    
    maturity_dates = pd.to_datetime(work[maturity_col], errors="coerce")
    target_year = pd.Timestamp.today().year if year is None else int(year)

    month = maturity_dates.dt.month
    day = maturity_dates.dt.day
    freq_series = pd.to_numeric(work[freq_col], errors="coerce").fillna(1).astype(int)

    first_of_month = pd.to_datetime(
        {"year": target_year, "month": month, "day": 1},
        errors="coerce",
    )
    month_end_day = (first_of_month + pd.offsets.MonthEnd(1)).dt.day
    safe_day = np.minimum(day, month_end_day)

    coupon_date_for_year = pd.to_datetime(
        {"year": target_year, "month": month, "day": safe_day},
        errors="coerce",
    )

    # Generate multiple coupon dates per year based on frequency
    all_rows = []
    for idx, row in work.iterrows():
        freq_val = int(freq_series.iloc[idx])
        freq_val = max(1, freq_val)  # ensure at least 1
        
        base_date = coupon_date_for_year.iloc[idx]
        mat_date = maturity_dates.iloc[idx]
        
        # Generate coupon dates for each period in the year
        months_per_period = 12 / freq_val
        
        for period in range(freq_val):
            # Calculate the month offset for this period
            months_offset = int(period * months_per_period)
            period_date = base_date + pd.DateOffset(months=months_offset)
            
            # Handle shift_past_coupon_day_to_next_year
            if shift_past_coupon_day_to_next_year:
                today = pd.Timestamp.today().normalize()
                if period_date < today and mat_date >= period_date + pd.DateOffset(years=1):
                    period_date = period_date + pd.DateOffset(years=1)
            
            # Match legacy trade-day logic used by collect_coupon_payment_days_old.
            weekday = period_date.day_name()[:3].lower()
            offset_days = {'sat': 2, 'sun': 3, 'mon': 4}.get(weekday, 2)
            trade_day = period_date - pd.Timedelta(days=offset_days)
            
            row_dict = {
                "coupon_payment_day": period_date.strftime("%d-%m"),
                "coupon_weekday": weekday,
                "coupon_payment_date_for_year": period_date,
                "coupon_year": period_date.year,
                "coupon_period": period + 1,
                "coupon_frequency": freq_val,
                "isin": row.get(isin_col) if isin_col in work.columns else pd.NA,
                "bond_description": row.get(description_col) if description_col in work.columns else pd.NA,
                "maturity": mat_date,
                "country": row.get('country', pd.NA),
                "coupon_trade_day": trade_day,
            }
            all_rows.append(row_dict)
    
    if not all_rows:
        return pd.DataFrame()  # Return empty DataFrame if no coupon-paying bonds
    
    result = pd.DataFrame(all_rows)
    result = result.dropna(subset=["coupon_payment_day"])
    
    if unique:
        return sorted(result["coupon_payment_day"].unique().tolist())

    return result.sort_values(["coupon_payment_day", "isin"]).reset_index(drop=True)

def findClosestBond(pf, target_bond_isin=None, target_bond_kriterum_value=None, country='DE', kriterium='rlz', isin_only=False, value_only=False):
    """
    Find the closest bond in the portfolio based on a specific criterion.
    IF target_bond_kriterum_value is provided or target_bond_isin is not in pf,
       it will be used instead of looking up the value from the target bond.   
    """
    if country == None:
        country = 'DE'
    target_bond= pf.query("isin == @target_bond_isin").reset_index(drop=True)
    if target_bond_kriterum_value is not None:
        kriterium_wert = target_bond_kriterum_value
    else:
        kriterium_wert = target_bond[kriterium].values[0]

    auswahl = pf.query("country == @country").reset_index(drop=True)
    auswahl['diff'] = (auswahl[kriterium]-kriterium_wert).abs()
    auswahl = auswahl.sort_values('diff').reset_index(drop=True)

    if auswahl.shape[0]==0:
        return
    if isin_only:
        return auswahl.head(1)['isin'].values[0]
    if value_only:
        return auswahl.head(1)[kriterium].values[0]
    return auswahl.head(1)


