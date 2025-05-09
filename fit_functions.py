import pandas as pd
import numpy as np
import fitparse
import math
import plotnine as p9
import os

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
    return raw

def calc_summary(raw):
    duration = raw.groupby(['km','source'])['sec'].agg(lambda x: x.iloc[-1] - x.iloc[0]).reset_index()
    distance = raw.groupby(['km','source'])[['km','source','distance']].nth(-1).reset_index(drop=True)

    distance['diff'] = distance.groupby('source')['distance'].diff(1)
    distance['diff'] = distance['diff'].fillna(distance['distance'])
    distance = distance.drop('distance', axis=1).rename(columns={'diff':'distance'})
    summary = raw.groupby(['km','source']).agg({'hr':'mean','step_length':'mean' ,'cadence':'mean','power':'mean'}).reset_index(drop=False)
    summary = summary.merge(duration, on=['km','source'], how='left').merge(distance, on=['km','source'], how='left')
    summary['sec_km'] = summary['sec'].div(summary['distance']).mul(1000)
    summary['kmh'] = (1/summary['sec_km']).mul(3600)
    summary['cadence'] = summary['cadence'].mul(2)
    summary=summary.sort_values(['source','km']).reset_index(drop=True)
    return summary

def plotSummary_v_hr(df):
    df = df.head(-1).tail(-1).reset_index(drop=True)
    p=(p9.ggplot(df)
    +p9.geom_point(p9.aes(x='kmh',y='hr', color='km')))
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