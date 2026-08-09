from pathlib import Path
import pandas as pd
import numpy as np
import sys
import os
import io
import warnings
import warnings
import plotnine as p9
import country_converter as coco
import skimpy
import re

try:
    from . import passiv_funktionen
except ImportError:
    import passiv_funktionen
try:
    from . import passiv_rlz
except ImportError:
    import passiv_rlz
try:
    from . import passiv_bond_values
except ImportError:
    import passiv_bond_values


from scipy.interpolate import UnivariateSpline
from datetime import datetime, timedelta, date
from collections import Counter
path_root = Path(os.path.realpath(__file__)).parents[2]
sys.path.append(str(path_root))

def keydur3(ttm: float, coupon: float, yld: float, frq: float,
        krates = [1,3,5,7,10,15,30], dur_target= None):
    
    # add present and far future
    kr = np.concatenate(([0], np.array(krates), [10e3]))
    
    # vector of points of time of cash flows
    t = np.arange(ttm - np.floor(ttm), ttm+1/frq, 1/frq)

    # cash flows
    # coupons
    cf = np.full_like(t, coupon/frq/100)
    # principal at final payment day
    cf[-1] = cf[-1] + 1

    # discount the cash flows 
    dcf =  cf *  ( (1+yld/100) ** (-t) )
    
    # init matrix of weights
    w = np.zeros([len(kr), len(t)])

    # index of (higher) kr where each CF is located
    ii = np.digitize(t, kr, right=True)

    for i in range(len(ii)):
        j = ii[i]
        w[j-1,i] = 1 - (t[i]-kr[j-1])/(kr[j]-kr[j-1])
        w[j,i] = 1 - w[j-1,i]
    
    kd = np.sum(t * dcf * w, axis=1)/np.sum(dcf *w)

    if dur_target:
        kd = kd/np.sum(kd) * dur_target

    kd[1] = kd[1] + kd[0]
    kd[-2] = kd[-2] + kd[-1]

    kd = kd[1:-1]

    return kd

#def marktwert(cpn,yld,rlz,tilgung):
    yld = yld/100
    if yld ==0:
        yld=.000001
    preis = cpn/yld+(tilgung-cpn/yld)*(1+yld)**(-rlz)
    return preis

def bm_files_pfad():
    # Prefer the actual module location (.../_passiv/libraries/passiv_import_data.py).
    module_path = Path(__file__).resolve()
    passiv_path = module_path.parent.parent
    bm_files_path = passiv_path / 'bm_files'
    if bm_files_path.exists():
        return bm_files_path

    # Fallback: rebuild path from the first "\\Rates\\" anchor if available.
    module_path_str = str(module_path)
    if '\\Rates\\' in module_path_str:
        return Path(module_path_str.split('\\Rates\\')[0] + '\\Rates\\python\\myg\\_passiv\\bm_files')

    # Last resort keeps previous behavior of returning a deterministic path.
    return bm_files_path
    
def __most_common_date_format(date_series):
    date_series = date_series.astype('str')
    date_formats = [
        '%Y-%m-%d',    # 2025-08-26
        '%d-%b-%y',    # 26-Aug-25 (2-digit year - check first)
        '%d-%B-%y',    # 26-August-25 (2-digit year - check first)
        '%y-%m-%d',    # 25-08-26 (2-digit year - check first)
        '%d-%m-%y',    # 30-12-25 (2-digit year - check first)
        '%d-%b-%Y',    # 26-Aug-2025 (4-digit year - check after)
        '%d-%B-%Y',    # 26-August-2025 (4-digit year - check after)
        '%d-%m-%Y',    # 26-08-2025
        '%m-%d-%Y',    # 08-26-2025
        '%b-%d-%Y',   # Aug-26-2025
        '%B-%d-%Y',   # August-26-2025
    ]

    detected_formats = []

    for date_str in date_series.dropna():
        for fmt in date_formats:
            try:
                _ = datetime.strptime(date_str, fmt)
                detected_formats.append(fmt)
                break
            except ValueError:
                continue

    if not detected_formats:
        return None  # No format matched

    most_common_fmt = Counter(detected_formats).most_common(1)[0][0]
    return most_common_fmt

def __count_commas_per_line(file_path):
    counts = []
    with open(file_path, 'r', encoding='utf-8') as file:
        for line_num, line in enumerate(file, 1):
            comma_count = line.count(',')
            counts.append({'line': line_num, 'comma_count': comma_count})

    df = pd.DataFrame(counts)
    return df


def __parse_maturity_column(maturity_series, fallback_format=None, warning=False):
    maturity = maturity_series.astype('string').str.strip()

    if fallback_format is not None:
        parsed = pd.to_datetime(maturity, format=fallback_format, errors='coerce')
    else:
        parsed = pd.Series(pd.NaT, index=maturity.index)

    remaining = parsed.isna() & maturity.notna() & (maturity != '')
    if remaining.any():
        mixed_formats = [
            '%d-%b-%y',
            '%d-%b-%Y',
            '%d-%B-%y',
            '%d-%B-%Y',
            '%d-%m-%y',
            '%d-%m-%Y',
            '%m-%d-%Y',
            '%y-%m-%d',
            '%Y-%m-%d',
        ]
        for fmt in mixed_formats:
            still_remaining = remaining & parsed.isna()
            if not still_remaining.any():
                break
            parsed.loc[still_remaining] = pd.to_datetime(
                maturity.loc[still_remaining],
                format=fmt,
                errors='coerce',
            )

    remaining = parsed.isna() & maturity.notna() & (maturity != '')
    if remaining.any():
        if warning:
            parsed.loc[remaining] = pd.to_datetime(maturity.loc[remaining], errors='coerce', dayfirst=True)
        else:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    'ignore',
                    message='Could not infer format, so each element will be parsed individually, falling back to `dateutil`.*',
                    category=UserWarning,
                )
                parsed.loc[remaining] = pd.to_datetime(maturity.loc[remaining], errors='coerce', dayfirst=True)

    return parsed

def import_data_tidy(datum = None, 
                     krates = [7, 10, 15, 20, 35, 50], 
                     mat_sect=None, 
                     pfad=None, 
                     file_override = None,
                     verbose=False, 
                     countries = ['AT', 'BE', 'CY', 'DE', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PT', 'SI', 'SK'],
                     correctdate=False, 
                     preview = False, 
                     problematic = True, 
                     provider='jpm'):
    
    krds = ['krd' + (f'0{item}' if item < 10 else str(item)) for item in krates]
    jpm_bm = import_data(datum=datum, 
                         krates=krates, 
                         mat_sect=mat_sect, 
                         pfad=pfad, 
                         file_override = file_override,
                         correctdate=correctdate, 
                         countries=countries, 
                         verbose=verbose, 
                         preview=preview,
                         problematic=problematic,
                         provider=provider)
    jpm_bm = (jpm_bm.melt(id_vars=[item for item in jpm_bm.columns.to_list() if item not in krds], value_vars= krds)).reset_index(drop=True)
    return jpm_bm

def __find_datei(datum=None, 
                 pfad=None, 
                 file_override = None,
                 verbose=False, 
                 correctdate=False, 
                 provider='jpm', 
                 preview=False):
    if file_override==None:

        if pfad==None:
            #pfad = '//atrfs200.wien.rbgat.net/middleware-p/indexprovider/jpm/gov/incoming/'
            pfad = Path(bm_files_pfad(),provider)
        if provider!=None:
            provider = provider.lower()
        if provider!='jpm':
            correctdate=False
            preview=False

        dateien = os.listdir(pfad)

        if provider == 'jpm':
            dateien = [datei for datei in dateien if 'GBROAD' in datei]
        if provider == 'ice':
            dateien = [datei for datei in dateien if 'EG00' in datei]
        
        if preview == False:
            dateien = [datei for datei in dateien if not 'PRE' in datei]
        else:
            dateien = [datei for datei in dateien if 'PRE' in datei]

        if len(dateien)>0:
            dateien = pd.DataFrame(dateien, columns=['name'])
            dateien['datum'] = dateien['name'].str[-10:].str[0:6]
            
            dateien['datum'] = dateien['datum'].astype('str')
            dateien['datum'] = '20'+dateien['datum']
            
            if datum!=None:
                datei = dateien.query("datum == @datum").reset_index(drop=True)
            else:
                datei = dateien.sort_values('datum', ascending=True).tail(1)        
                datum = datei.head(1)['datum'].iloc[0]
            if datei.shape[0]>0:
                if verbose:
                    print(f'...found: {datei.shape[0]} file[s] with {datum} as date...')
                datei = Path(pfad,datei.head(1)['name'].iloc[0])
            else:
                danach = dateien.query("datum>@datum").sort_values('datum').reset_index(drop=True)
                if danach.shape[0]==0:
                    danach = None
                else:
                    danach = danach['datum'].head(1).iloc[0]
                davor = dateien.query("datum<@datum").sort_values('datum').reset_index(drop=True)
                if davor.shape[0]==0:
                    davor = None
                else:
                    davor = davor['datum'].tail(1).iloc[0]
                if verbose:
                    print(f"Date {datum} not found!")
                    print(f"...avaliable before: {davor}")
                    print(f"...avaliable after: {danach}")
                return davor, 0

        else:
            print(f"No benchmark files in Directory:{pfad}")
            return datum, 0
    else:
        datei = file_override
        datum = re.search(r'\d{4}-\d{2}-\d{2}', datei)
        if datum==None:
            datum = re.search(r'\d{4}\d{2}\d{2}', datei)   
        if datum!=None:
            datum = datum.group().replace('-', '')
        else:
            datum = '19740629'

    datum_pd = pd.to_datetime(datum, format='%Y%m%d')

    if verbose:
        print(f'File: {datei}')
        print(f'Date in Filename: {datum}')
        
    if correctdate:
        with open(datei, 'r') as file:
            first_line = file.readline()
        first_line=first_line[-9:]
        first_line=first_line.strip()
        if datum!=first_line:
            print(f'{datum}), {first_line}')
            datum_pd = pd.to_datetime(first_line, format='%Y%m%d')

    return datum_pd, datei

def import_data(datum = None, 
                krates = [3, 5, 7, 10, 15, 30, 50], 
                mat_sect = ['1-3', '3-5', '5-7', '7-10', '10+'], 
                pfad=None, 
                file_override = None,
                verbose=False, 
                preset='emu',
                countries=None,
                currencies=None,
                correctdate=False,
                preview = False,
                problematic = True,
                provider = 'jpm',
                jpm_weight_col = 'weight_%_daily_usd_rtrn',
                add_datum_as_col = False,
                add_return_figures = False,
                warning = False,
                engine = 'python'):
    """ datum: YYYMMDD 20250723 (kein datum = letztes datum)
        krates: list [3, 5, 7, 10, 15, 30, 50]
        mat_sect: eines aus [None, '1-3', '3-5', '5-7', '7-10', '10+'] (nur bei provider jpm)
        pfad: der Pfad wo die BM Dateien liegen
        file_override: eine bestimmte Datei inkl. vollem Pfad
        preset: 'emu' oder 'global'
        countries: eines oder mehrere iso2: z.B.: ['AT', 'BE', 'CY', 'DE']
        correctdate: prüft ob das Datum im Dateiamen auch jenes in der Datei ist und korrigiert das ggf.
        preview: es handelt sich um eine Preview Datei (legacy)
        problematic: falls das Datum parsen nicht funktioniert auf True setzen, ab 27.11.2025 Standard
        provider: 'jpm' oder 'ice'
        jpm_weight_col: welche spalte wird als Gewichtsspalte genommen? 'weight_%_daily_usd_rtrn' (default) oder 'weight_%_daily_stats'
        warning: True/False zum Ein-/Ausschalten des spezifischen pandas-Warnings "Could not infer format ... falling back to `dateutil`"
        engine: 'python' oder 'c' zum öffnen der .csv
    """
    if isinstance(krates, list) and krates and isinstance(krates[0], list):
        krates = krates[0]

    if isinstance(countries, list) and countries and isinstance(countries[0], list):
        countries = countries[0]

    if countries!=None:
        preset=None
    if preset!=None:
        preset=preset.lower()
    if preset=='emu':
        countries=['AT', 'BE', 'BG' ,'CY', 'DE', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PT', 'SI', 'SK']
    if preset=='global':
        countries=['AU','BE','CA','DE','DK','ES','FR','GB','IT','JP','NL','SE','US']

    if provider!=None:
        provider = provider.lower()
    if provider!='jpm':
        problematic=False
        mat_sect=['1-3', '3-5', '5-7', '7-10', '10+']

    if mat_sect==None:
        mat_sect=['1-3', '3-5', '5-7', '7-10', '10+']

    krds = ['krd' + (f'0{item}' if item < 10 else str(item)) for item in krates]

    datum, datei = __find_datei(datum=datum, 
                                pfad=pfad,
                                file_override=file_override,
                                verbose=verbose, 
                                correctdate=correctdate, 
                                preview=preview, 
                                provider=provider)
    if datei ==0:
        print(f'{datum} not found or no access!')
        return

    if not os.path.isfile(datei):
        print(f'{datei} not found or no access!')
        return

    if (engine==None) or (engine!='python'):
        engine = 'c'

    if provider=='jpm':
        skiprows=1
    if provider=='ice':
        skiprows=3

    if preview or problematic:
        with open(datei, 'r') as file:
            content = file.read()
            content = re.sub(r',+$', ',', content, flags=re.MULTILINE)
            # content = content.replace(',,', ',')
            content = io.StringIO(content)
        bm = pd.read_csv(content, skiprows=skiprows, engine=engine)
    else:
        bm = pd.read_csv(datei, skiprows=skiprows, engine=engine)
    
    bm = skimpy.clean_columns(bm)
    
    if provider=='jpm':
        if jpm_weight_col=='weight_%_daily_stats':
            bm = bm.rename(columns={'weight_%_daily_stats':'weight'})
            if verbose:
                print("Using 'weight_%_daily_stats' as weight (NOT 'weight_%_daily_usd_rtrn')")
        else:
            bm = bm.rename(columns={'weight_%_daily_usd_rtrn':'weight'})
            if verbose:
                print("Using 'weight_%_daily_usd_rtrn' as weight (NOT 'weight_%_daily_stats')")

        bm['mat_sect'] = bm['mat_sect'].str.replace("'","")

        
    if provider=='ice':
        bm = bm.rename(columns={'isin_number':'isin',
                        'description_1':'bond_description',
                        'iso_currency':'currency',
                        'accrued_interest':'accr_int',
                        'maturity_date':'maturity',
                        'iso_country':'country',
                        'mkt_%_index_wght':'weight',
                        'modified_dur':'mod_dur',
                        'macaulay_dur':'mac_dur',
                        'current_coupon':'coupon',
                        'yld_to_maturity':'yield',
                        'face_value_loc':'outs_loc_mm'})

        bm['freq'] = np.where(bm['country']=='IT',2,1)
    
    bm['freq'] = np.where(bm['freq']==0,1,bm['freq'])


    if countries!=None:
        bm = bm[bm['country'].isin(countries)].reset_index(drop=True)
    if currencies!=None:
        bm = bm[bm['currency'].isin(currencies)].reset_index(drop=True)

    bm = bm.query("not isin.isnull()").reset_index(drop=True)

    if problematic: #jpm only
        replacements = {'Mrz': 'Mar', 
                        'Mai': 'May', 
                        'Okt': 'Oct', 
                        'Dez': 'Dec', 
                        '. ': '-', 
                        '.': '-', 
                        ' ': '-', 
                        '/': '-'}
        for old, new in replacements.items():
            bm['maturity'] = bm['maturity'].str.replace(old, new)
            bm['issue_date'] = bm['issue_date'].str.replace(old, new)

        dateformat = __most_common_date_format(bm['maturity'])
        if verbose:
            print(f"date format: {dateformat}")
        bm['maturity'] = __parse_maturity_column(bm['maturity'], fallback_format=dateformat, warning=warning)
        bm['maturity'] = bm['maturity'].map(lambda date: date.replace(year=date.year + 100) if date.year < 2000 else date)
        bm['maturity'] = bm['maturity'].map(lambda date: date.replace(year=date.year + 100) if date.year < datum.year else date)

        bm['issue_date'] = __parse_maturity_column(bm['issue_date'], fallback_format=dateformat, warning=warning)
        
    else:
        if provider=='jpm':
            bm['maturity'] = pd.to_datetime(bm['maturity'], format="%d %b %Y")
            bm['issue_date'] = pd.to_datetime(bm['issue_date'], format="%d %b %Y")
        if provider=='ice':
            bm['maturity'] = pd.to_datetime(bm['maturity'], format='%m/%d/%Y')


    to_drop = [item for item in bm.columns.to_list() if 'unnamed' in item]
    bm = bm.drop(to_drop,axis=1)

    settlement_shift = 2
    if pd.to_datetime(datum).weekday() == 3:  # Thursday
        settlement_shift = 4

    if pd.to_datetime(datum).weekday() == 4:  # Friday
        settlement_shift = 4

    settlement_date = pd.to_datetime(datum) + pd.DateOffset(days=settlement_shift)

    bm['rlz'] = bm.apply(lambda row: passiv_rlz.rlz(start_date=settlement_date,
                                                    end_date=row['maturity'],
                                                    method='anniversary',
                                                    freq=row['freq']), axis=1)
    #bm['rlz'] = bm['maturity'].apply(lambda x: passiv_funktionen.get_year_fraction_exact(settlement_date, x, method='bloomberg'))
    #bm['rlz'] = ((bm['maturity'] - pd.to_datetime(datum)).dt.days / 365) - settlement_shift
    bm['rlz'] = bm['rlz'].astype('float64')
    bm = bm.sort_values(['country','rlz']).reset_index(drop=True)
    
    a = bm[['country', 'rlz', 'yield']]

    def fit_spline(group):
        if len(group) < 4:  # Check if there are fewer than 4 data points
            return pd.Series([None] * len(group), index=group.index)
        spline = UnivariateSpline(x=group['rlz'], y=group['yield'], s=5)
        return pd.Series(spline(group['rlz']), index=group.index)

    result = a.groupby('country').apply(fit_spline,include_groups=False).reset_index()

    bm['yield_sm'] = result.rename(columns={0: 'smoothed_yield'})['smoothed_yield'].astype('float64').round(4)
    
    if provider == 'jpm':
        if isinstance(mat_sect, str):
            mat_sect = [mat_sect]

        if all(mat in ['1-3', '3-5', '5-7', '7-10', '10+'] for mat in mat_sect):
            bm = bm.query("mat_sect in @mat_sect").reset_index(drop=True)
        else:
            if verbose:
                print(f"{mat_sect} not in {['1-3', '3-5', '5-7', '7-10', '10+']}")
            mat_sect = ['1-3', '3-5', '5-7', '7-10', '10+']
    else:
        mat_sect = ['1-3', '3-5', '5-7', '7-10', '10+']

    bm['weight'] = bm['weight'].astype('float64')
    bm['coupon'] = bm['coupon'].astype('float64')
    bm['freq'] = bm['freq'].astype('float64')

    bm['weight'] = bm['weight']/bm['weight'].sum()*100
    bm = bm.sort_values(['country','rlz']).reset_index(drop=True)

    if provider=='jpm':
        bm['convexity']=bm['convexity'].astype('float64').div(100)


    if provider=='jpm':
        if add_return_figures:
            bm=bm[['isin','bond_description','liquidity','maturity','mat_sect','price','accr_int','country',
                        'weight','rlz','yield','yield_sm','coupon','issue_date','mac_dur','mod_dur','convexity','freq','outs_loc_mm','currency',
                        '1_d_rtn', 'mtd_rtn', '12_m_rtn', 'ytd_rtn',
                        '1_d_rtn_usd', 'mtd_rtn_usd', '12_m_rtn_usd', 'ytd_rtn_usd', 
                        '1_d_rtn_eur', 'mtd_rtn_eur', '12_m_rtn_eur', 'ytd_rtn_eur']].reset_index(drop=True)
        else:
            bm=bm[['isin','bond_description','liquidity','maturity','mat_sect','price','accr_int','country',
                        'weight','rlz','yield','yield_sm','coupon','issue_date','mac_dur','mod_dur','convexity','freq','outs_loc_mm','currency']].reset_index(drop=True)
    if provider=='ice':
        bm=bm[['isin','bond_description','maturity','price','accr_int','country',
                     'weight','rlz','yield','yield_sm','coupon','mac_dur', 'mod_dur','freq','outs_loc_mm','currency']].reset_index(drop=True)

   # def calculate_macaulay_duration(settlement_date, maturity_date, coupon, yld, freq, 
   #                             first_coupon_type='regular', issue_date=None, 
   #                             discount_method='standard', compounding='annual', runden=5):

    bm['price_theo'] = bm.apply(lambda row: passiv_funktionen.calculate_bond_values(tilgung=100, 
                                                                                    coupon=row['coupon'], 
                                                                                    ytm=row['yield'], 
                                                                                    rlz=row['rlz'], 
                                                                                    freq=row['freq'])['price_theo'], axis=1)

    #bm['price_theo'] = bm.apply(lambda row: passiv_funktionen.marktwert(row['coupon'], row['yield'], row['rlz'], 100), axis=1)


    bm['diff'] = bm['price_theo']-bm['price']
    bm['dirty_theo'] = bm['price_theo']+bm['accr_int']
    bm[krds] = bm.apply(lambda row: keydur3(ttm=row['rlz'],
                                            coupon=row['coupon'],
                                            yld=row['yield'],
                                            frq=row['freq'],
                                            dur_target=row['mac_dur'],
                                            krates=krates), axis=1, result_type='expand')

    for col in bm.columns:
        if bm[col].dtype == 'object':  
            bm[col] = bm[col].str.strip()
    bm = bm.drop_duplicates().reset_index(drop=True)
    
    if add_datum_as_col:
        cols = bm.columns.to_list()
        bm['datum'] = datum
        bm = bm[['datum'] +cols]

    if verbose:
        print(f'Date: {datum.date()}')
        print(f'Provider: {provider}')
        print(f'Key Rates: {krds}')
        print(f'Maturity Buckets: {mat_sect}')
        print(f"Countries: {bm['country'].drop_duplicates().to_list()}")
        print(f'Number of Bonds: {bm.shape[0]}')
    return bm

def csv2german(datum=None, pfad=None, file_override=None, verbose=False, provider='jpm'):
    datum, datei = __find_datei(datum=datum, 
                                pfad=pfad,
                                file_override=file_override,
                                verbose=verbose, 
                                correctdate=False, 
                                preview=False, 
                                provider=provider)
    output_path = datei.parent
    output_name = datei.stem + '-german.csv'

    output_full = Path(output_path, 'german', output_name)

    with datei.open('r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace(',', ';').replace('.', ',')
    content = content.replace('Jan','Jän')
    content = content.replace('Mar','Mrz')
    content = content.replace('May','Mai')
    content = content.replace('Oct','Okt')
    content = content.replace('Dec','Dez')

    with output_full.open('w', encoding='latin-1') as f:
        f.write(content)
    return output_name


