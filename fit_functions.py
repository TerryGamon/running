import pandas as pd
import numpy as np
import fitparse
import math
import plotnine as p9
import os
import sys

def print_progress_bar(index, total, label1, label2, label3):
    n_bar = 50
    progress = index / total
    sys.stdout.write('\r')
    sys.stdout.write(f"[{'=' * int(n_bar * progress):{n_bar}s}] {int(100 * progress)}%  {label1} {label2} {label3}")
    sys.stdout.flush()


# Load the FIT file
def parse_fit(datei):

    fitfile = fitparse.FitFile(datei)
    xx=[]
    for record in fitfile.get_messages("record"):
        zeit = None
        hr = None
        power = None
        step_length = None
        cadence = None
        speed = None
        distance = None
        for data in record:
            if data.name=='timestamp':
                zeit = data.value
            if data.name=='heart_rate':
                hr = data.value
            if data.name=='distance':
                distance=data.value
            if data.name=='power':
                power = data.value
            if data.name=='step_length':
                step_length = data.value
            if data.name=='cadence':
                cadence = data.value 
            if data.name=='enhanced_speed':
                speed = data.value
            x = [zeit,distance, hr, power, step_length, cadence, speed]
        xx.append(x)

    raw= pd.DataFrame(xx, columns=['time','distance','hr','power','step_length','cadence','speed'])
    raw['km']=raw['distance'].apply(lambda x: math.floor(x/1000))
    raw['sec']=raw.index
    raw['kmh']=raw['speed'].mul(3.6)
    raw['source']=datei
    raw['datum']=pd.to_datetime(fit_date(datei))
    return raw

def fit_date(datei):
    fitfile = fitparse.FitFile(datei)
    for record in fitfile.get_messages('file_id'):
        datum = record.get_value('time_created')
        #datum = datum.date()
    return datum

def fit_sport(datei):
    fitfile = fitparse.FitFile(datei)

    for record in fitfile.get_messages('session'):
        sport = record.get_value('sport')
    return sport

def calc_summary(raw):
    duration = raw.groupby(['km','source','datum'])['sec'].agg(lambda x: x.iloc[-1] - x.iloc[0]).reset_index()
    distance = raw.groupby(['km','source','datum'])[['km','source','datum','distance']].nth(-1).reset_index(drop=True)

    distance['diff'] = distance.groupby('source')['distance'].diff(1)
    distance['diff'] = distance['diff'].fillna(distance['distance'])
    distance = distance.drop('distance', axis=1).rename(columns={'diff':'distance'})
    summary = raw.groupby(['km','source','datum']).agg({'hr':'mean','step_length':'mean' ,'cadence':'mean','power':'mean'}).reset_index(drop=False)
    summary = summary.merge(duration, on=['km','source','datum'], how='left').merge(distance, on=['km','source','datum'], how='left')
    summary['sec_km'] = summary['sec'].div(summary['distance']).mul(1000)
    summary['kmh'] = (1/summary['sec_km']).mul(3600)
    summary['cadence'] = summary['cadence'].mul(2)
    summary=summary.sort_values(['source','km']).reset_index(drop=True)
    return summary

def plotSummary_v_hr(df):
    p=(p9.ggplot(df)
    +p9.geom_point(p9.aes(x='kmh',y='hr', color='jahr-monat'))
    +p9.geom_smooth(p9.aes(x='kmh',y='hr'), method='lm', se=False, size=.5, color='darkgray')
    +p9.scale_x_continuous(limits=[8,15])
    +p9.facet_wrap('~km')
    +p9.theme_bw()
    +p9.theme(figure_size=[16,9])
    +p9.labs(x='km/h',y='HR', title='HR vs. Geschwindigkeit nach gelaufenem km pro Monat')
    +p9.theme(legend_key=p9.element_blank())
    +p9.theme(legend_position='bottom',
              legend_title=p9.element_blank())
    +p9.theme(axis_text=p9.element_text(size=12))
    +p9.theme(strip_text=p9.element_text(size=12))
    )
    return p

def plotSummary_v_cadence(df):
    p=(p9.ggplot(df)
    +p9.geom_point(p9.aes(x='kmh',y='cadence')))
    return p



# for record in fitfile.get_messages("record"):
#     for data in record:
#         if data.units:
#             print(" * {}: {} ({})".format(data.name, data.value, data.units))
#         else:
#             print(" * {}: {}".format(data.name, data.value))
#     print('-------------------')