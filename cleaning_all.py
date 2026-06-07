import re
import sys
import pandas as pd
import numpy as np
from typing import Optional
from sqlalchemy import create_engine


PROMO_WORDS = re.compile(
    r'\b(акция|хит|новинка|распродажа|скидка|опт|дешево|выгодно|топ|супер|лучший)\b',
    re.IGNORECASE
)


def drop_empty_columns(df: pd.DataFrame) -> pd.DataFrame:
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        print(f"Удалены пустые столбцы: {empty_cols}")
    return df.drop(columns=empty_cols)


def drop_duplicates(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    before = len(df)
    df = df.drop_duplicates()
    removed = before - len(df)
    if removed:
        print(f"  [{source_name}] Удалено дубликатов строк: {removed}")
    return df


def normalized_name(text: str) -> Optional[str]:
    if not isinstance(text, str) or not text.strip():
        return None
    s = text.strip()
    s = re.sub(r'[!@#$%^&*]+', '', s)  
    s = PROMO_WORDS.sub('', s)           
    s = re.sub(r'\s{2,}', ' ', s)         
    s = s.strip(' ,;-')
    s = s.lower()                         
    return s if s else None


BRAND_DICT: dict[str, Optional[str]] = {
 
    '10Pr':                     None,
    '12.00R20-20Pr':            None,
    '14.00R25':                 None,
    '265/70R15':                None,
    '385/65R22.5-24Pr':         None,
    '4S':                       None,
    '888':                      None,
    'L':                        None,
    'R16':                      None,
    'R17':                      None,
    'R18':                      None,
    'En1250':                   None,
    'K700':                     None,
    'Ci-4':                     None,
    'Ci4':                      None,
    'Авиационное':              None,
    'Авторезина':               None,
    'Аксессуар':                None,
    'Без Бренда':               None,
    'Воздушный':                None,
    'Грузовая':                 None,
    'Дизельное':                None,
    'Дизельных':                None,
    'Кабины':                   None,
    'Корпус':                   None,
    'Крышка':                   None,
    'Легковая':                 None,
    'Маслянный':                None,
    'Масляный':                 None,
    'Минеральное':              None,
    'Осушителя':                None,
    'Охлаждающей':              None,
    'Полностью':                None,
    'Полусинтетическое':        None,
    'Приборное':                None,
    'Противоизносное':          None,
    'Салона':                   None,
    'Салонный':                 None,
    'Синтетическое':            None,
    'Системы':                  None,
    'Топливный':                None,
    'Трансмиссионный':          None,
    'Четырехтактных':           None,
    'Шинf':                     None,
    'Шинокомплект':             None,
    'Шины':                     None,
    'На':                       None,
    'С':                        None,
    'Аkпп':                     None,

    **{f'Рц-{s}': None for s in [
        '00004012','00004242','00004248','00004994',
        '00007141','00007142','00007143','00007145','00007146','00007147',
        '00007348','00007349','00007841','00007852',
        '00007881','00007882','00007884','00007949',
        '00008127','00008128','00008307','00008308',
        '00008314','00008315','00008317','00008322','00008326','00008633',
    ]},
    'Х0000000234':              None,
    'Це000113':                 None,
    'Цеоо0007109':              None,
    'Фвуа-100А-24':             None,
    'Рц-00004012':              None,  
    'A+':                       'A+',
    'A-Gressor':                'A-Gressor',
    'A.D.A.L Auto':             'A.D.A.L Auto',
    'Aa-Top':                   'Aa-Top',
    'Abe':                      'Abe',
    'Accelera':                 'Accelera',
    'Acdelco':                  'ACDelco',
    'ACDelco':                  'ACDelco',
    'Ace-Q':                    'Ace-Q',
    'Acemark':                  'Acemark',
    'Achilles':                 'Achilles',
    'Adaoer':                   'Adaoer',
    'Adcon':                    'Adcon',
    'Addinol':                  'Addinol',
    'ADDINOL':                  'Addinol',
    'Aderenza':                 'Aderenza',
    'Advance':                  'Advance',
    'Aeolus':                   'Aeolus',
    'AEOLUS':                   'Aeolus',
    'Afinol':                   'Afinol',
    'Agate':                    'Agate',
    'Aircleaner':               'Aircleaner',
    'Aisan':                    'Aisan',
    'Aito':                     'Aito',
    'Alliance':                 'Alliance',
    'Allsun':                   'Allsun',
    'Alnsu':                    'Alnsu',
    "Alpha'S":                  "Alpha'S",
    'Altenzo':                  'Altenzo',
    'Amd':                      'Amd',
    'America':                  'America',
    'Amtel':                    'Amtel',
    'AMTEL':                    'Amtel',
    'Anjie':                    'Anjie',
    'Annaite':                  'Annaite',
    'Antares':                  'Antares',
    'Antyre':                   'Antyre',
    'Aobi':                     'Aobi',
    'Aokly':                    'Aokly',
    'Aonaite':                  'Aonaite',
    'Aosen':                    'Aosen',
    'Aoteli':                   'Aoteli',
    'Api':                      'Api',
    'Aplus':                    'Aplus',
    'Apollo':                   'Apollo',
    'APOLLO':                   'Apollo',
    'Aptany':                   'Aptany',
    'Aqbp':                     'Aqbp',
    'Aral':                     'Aral',
    'ARAL':                     'Aral',
    'Arctic Claw':              'Arctic Claw',
    'Arduzza':                  'Arduzza',
    'Areol':                    'Areol',
    'AREOL':                    'Areol',
    'Arirang':                  'Arirang',
    'Arivo':                    'Arivo',
    'Arizonian':                'Arizonian',
    'Armour':                   'Armour',
    'Armstrong':                'Armstrong',
    'Artum':                    'Artum',
    'Asam':                     'Asam',
    'Ashika':                   'Ashika',
    'Asin':                     'Asin',
    'Atlander':                 'Atlander',
    'Atlas':                    'Atlas',
    'Atlas Copco':              'Atlas Copco',
    'Att':                      'Att',
    'Attar':                    'Attar',
    'Atturo':                   'Atturo',
    'Aufine':                   'Aufine',
    'Auger':                    'Auger',
    'Auplus':                   'Auplus',
    'Aurora':                   'Aurora',
    'Austone':                  'Austone',
    'Autogreen':                'Autogreen',
    'Autogrip':                 'Autogrip',
    'Autoguard':                'Autoguard',
    'Autopower':                'Autopower',
    'Autostone':                'Autostone',
    'Avantech':                 'Avantech',
    'Avatr':                    'Avatr',
    'Avatyre':                  'Avatyre',
    'Avon':                     'Avon',
    'Aккумулятор':              None,
    'Baldwin':                  'Baldwin',
    'Banner':                   'Banner',
    'Bardahl':                  'Bardahl',
    'BARDAHL':                  'Bardahl',
    'Bars':                     'Bars',
    'Barum':                    'Barum',
    'BARUM':                    'Barum',
    'Batrex':                   'Batrex',
    'Bearway':                  'Bearway',
    'Belshina':                 'Belshina',
    'Белшина':                  'Belshina',
    'Benchmarkt':               'Benchmarkt',
    'Berlin':                   'Berlin',
    'Berlin Tires':             'Berlin Tires',
    'Bfgoodrich':               'BFGoodrich',
    'BFGoodrich':               'BFGoodrich',
    'BFGOODRICH':               'BFGoodrich',
    'Bibicare':                 'Bibicare',
    'Big':                      'Big',
    'Big Filter':               'Big Filter',
    'Big-O':                    'Big-O',
    'Bkt':                      'BKT',
    'BKT':                      'BKT',
    'Black':                    'Black',
    'Black Arrow':              'Black Arrow',
    'Blackarrow':               'Black Arrow',   
    'Blackhawk':                'Blackhawk',
    'Blacklion':                'Blacklion',
    'Blackstone':               'Blackstone',
    'Blue':                     'Blue',
    'Blue Print':               'Blue Print',
    'Bm-Motorsport':            'BM-Motorsport',
    'Bmw':                      'BMW',
    'BMW':                      'BMW',
    'Bogap':                    'Bogap',
    'Bontyre':                  'Bontyre',
    'Borsehung':                'Borsehung',
    'Bosch':                    'Bosch',
    'BOSCH':                    'Bosch',
    'Bosm':                     'Bosm',
    'Boto':                     'Boto',
    'Bpi Sports':               'BPI Sports',
    'Brasa':                    'Brasa',
    'Brave':                    'Brave',
    'Bridgestone':              'Bridgestone',
    'BRIDGESTONE':              'Bridgestone',
    'bridgestone':              'Bridgestone',
    'Briss':                    'Briss',
    'Briway':                   'Briway',
    'Byd':                      'BYD',
    'BYD':                      'BYD',
    'C.N.R.G.':                 'C.N.R.G.',
    'CNRG':                     'C.N.R.G.',
    'Cachland':                 'Cachland',
    'Camso':                    'Camso',
    'Capitol':                  'Capitol',
    'Carex':                    'Carex',
    'Carleo':                   'Carleo',
    'Carps':                    'Carps',
    'Carstation':               'Carstation',
    'Cartronic':                'Cartronic',
    'Carville Racing':          'Carville Racing',
    'Castrol':                  'Castrol',
    'CASTROL':                  'Castrol',
    'castrol':                  'Castrol',
    'Cat':                      'CAT',
    'CAT':                      'CAT',
    'Ceat':                     'CEAT',
    'CEAT':                     'CEAT',
    'Centara':                  'Centara',
    'Cf':                       'CF',
    'Ch-Noble':                 'Ch-Noble',
    'Changan':                  'Changan',
    'Changfeng':                'Changfeng',
    'Chao Yang':                'Chaoyang',   
    'Chaoyang':                 'Chaoyang',
    'CHAOYANG':                 'Chaoyang',
    'Chaoyang; Constancy':      'Chaoyang',   
    'Character':                'Character',
    'Charmhoo':                 'Charmhoo',
    'Chempioil':                'Chempioil',
    'CHEMPIOIL':                'Chempioil',
    'Chengshan':                'Chengshan',
    'Chery':                    'Chery',
    'Chery/Exeed':              'Chery',
    'Citroen/Peugeot':          'Citroen/Peugeot',
    'Peugeot-Citroen':          'Citroen/Peugeot',
    'Cnab':                     'Cnab',
    'Combo':                    'Combo',
    'Comforser':                'Comforser',
    'Comma':                    'Comma',
    'COMMA':                    'Comma',
    'Compasal':                 'Compasal',
    'Composit':                 'Composit',
    'Constancy':                'Constancy',
    'Contact':                  'Contact',
    'Continental':              'Continental',
    'CONTINENTAL':              'Continental',
    'continental':              'Continental',
    'Contyre':                  'Contyre',
    'Cooper':                   'Cooper',
    'COOPER':                   'Cooper',
    'Cordiant':                 'Cordiant',
    'CORDIANT':                 'Cordiant',
    'cordiant':                 'Cordiant',
    'Cordovan':                 'Cordovan',
    'Corteco':                  'Corteco',
    'Cr':                       'CR',
    'Cratos':                   'Cratos',
    'Crona':                    'Crona',
    'Crossleader':              'Crossleader',
    'Cst':                      'CST',
    'CST':                      'CST',
    'Cummins':                  'Cummins',
    'Cworks':                   'Cworks',
    'Cyclone':                  'Cyclone',
    'Daewha':                   'Daewha',
    'Daewoo':                   'Daewoo',
    'DAEWOO':                   'Daewoo',
    'Daf':                      'DAF',
    'DAF':                      'DAF',
    'Daitei':                   'Daitei',
    'Davanti':                  'Davanti',
    'Dayton':                   'Dayton',
    'Dean':                     'Dean',
    'Debica':                   'Debica',
    'DEBICA':                   'Debica',
    'Deestone':                 'Deestone',
    'Definity':                 'Definity',
    'Deko':                     'Deko',
    'Deli':                     'Deli',
    'Delinte':                  'Delinte',
    'Delmax':                   'Delmax',
    'Delphi':                   'Delphi',
    'Delta':                    'Delta',
    'Denso':                    'Denso',
    'DENSO':                    'Denso',
    'Dextero':                  'Dextero',
    'Dfp Plast':                'DFP Plast',
    'Diamondback':              'Diamondback',
    'Dick Cepek':               'Dick Cepek',
    'Difa':                     'Difa',
    'Diplomat':                 'Diplomat',
    'Donaldson':                'Donaldson',
    'Double':                   'Double',
    'Double Coin':              'Double Coin',
    'Doublecoin':               'Double Coin',   
    'DOUBLECOIN':               'Double Coin',
    'Double Force':             'Double Force',
    'Double Road':              'Double Road',
    'Double Star':              'Double Star',
    'Doublestar':               'Double Star',   
    'DOUBLESTAR':               'Double Star',
    'Doubleking':               'Doubleking',
    'Doupro':                   'Doupro',
    'Dovroad':                  'Dovroad',
    'Drive':                    'Drive',
    'Dt Spare Parts':           'DT Spare Parts',
    'Dub':                      'Dub',
    'Dunlop':                   'Dunlop',
    'DUNLOP':                   'Dunlop',
    'Duraturn':                 'Duraturn',
    'Durun':                    'Durun',
    'Dw':                       'DW',
    'Dyf':                      'Dyf',
    'Dynamo':                   'Dynamo',
    'Ecotyre':                  'Ecotyre',
    'Effiplus':                 'Effiplus',
    'Eldorado':                 'Eldorado',
    'Elemfil':                  'Elemfil',
    'Elf':                      'Elf',
    'ELF':                      'Elf',
    'Ellerbrock':               'Ellerbrock',
    'Elring':                   'Elring',
    'ELRING':                   'Elring',
    'Emrald':                   'Emrald',
    'Eni':                      'Eni',
    'ENI':                      'Eni',
    'Esa-Tecar':                'Esa-Tecar',
    'Euro':                     'Euro',
    'Eurol':                    'Eurol',
    'Eurostart':                'Eurostart',
    'Eurotec':                  'Eurotec',
    'Euzkadi':                  'Euzkadi',
    'Evergreen':                'Evergreen',
    'Excel Japan':              'Excel Japan',
    'Exide':                    'Exide',
    'Exmile':                   'Exmile',
    'Ez; Carleo':               'Carleo',   
    'Falken':                   'Falken',
    'FALKEN':                   'Falken',
    'Fanfaro':                  'Fanfaro',
    'FANFARO':                  'Fanfaro',
    'Farroad':                  'Farroad',
    'Fb':                       'FB',
    'Fdr':                      'FDR',
    'Febest':                   'Febest',
    'Febi':                     'Febi',
    'FEBI':                     'Febi',
    'Federal':                  'Federal',
    'Fenix':                    'Fenix',
    'Fenox':                    'Fenox',
    'FENOX':                    'Fenox',
    'Fenva':                    'Fenva',
    'Fesite':                   'Fesite',
    'Fil':                      'Fil',
    'Fil Filter':               'Fil Filter',
    'Filterland':               'Filterland',
    'Filtron':                  'Filtron',
    'FILTRON':                  'Filtron',
    'Firemax':                  'Firemax',
    'Firenza':                  'Firenza',
    'Firestone':                'Firestone',
    'FIRESTONE':                'Firestone',
    'First Stop':               'First Stop',
    'Fleetguard':               'Fleetguard',
    'Foman':                    'Foman',
    'Ford':                     'Ford',
    'FORD':                     'Ford',
    'Forerunner':               'Forerunner',
    'Forever':                  'Forever',
    'Formula':                  'Formula',
    'Fortuna':                  'Fortuna',
    'Fortune':                  'Fortune',
    'FORTUNE':                  'Fortune',
    'Forward':                  'Forward',
    'Forza':                    'Forza',
    'Fram':                     'Fram',
    'FRAM':                     'Fram',
    'Freedom Drive':            'Freedom Drive',
    'FREEDOM DRIVE':            'Freedom Drive',
    'Frey':                     'Frey',
    'Friezza':                  'Friezza',
    'Fronway':                  'Fronway',
    'Fs':                       'FS',
    'Fuchs':                    'Fuchs',
    'FUCHS':                    'Fuchs',
    'Fuerdun':                  'Fuerdun',
    'Fukurawa':                 'Fukurawa',
    'Fulda':                    'Fulda',
    'FULDA':                    'Fulda',
    'Fullmax':                  'Fullmax',
    'Fullrun':                  'Fullrun',
    'Fullway':                  'Fullway',
    'Furo':                     'Furo',
    'Furukawa':                 'Furukawa',
    'Furukawa Battery':         'Furukawa Battery',
    'Fvp':                      'FVP',
    'G&L':                      'G&L',
    'G-Box':                    'G-Box',
    'G-Energy':                 'G-Energy',
    'G-energy':                 'G-Energy',
    'Galaxia':                  'Galaxia',
    'Galaxy':                   'Galaxy',
    'Gambera':                  'Gambera',
    'Gates':                    'Gates',
    'GATES':                    'Gates',
    'Gazpromneft':              'Gazpromneft',
    'Газпромнефть':             'Gazpromneft',   
    'Газпром Нефть':            'Gazpromneft',   
    'Газпром':                  'Gazpromneft',
    'Geely':                    'Geely',
    'General':                  'General',
    'General Motors':           'General Motors',
    'General Tire':             'General Tire',
    'Gerat':                    'Gerat',
    'German Gold':              'German Gold',
    'Gigawatt':                 'Gigawatt',
    'Gislaved':                 'Gislaved',
    'GISLAVED':                 'Gislaved',
    'Giti':                     'Giti',
    'GITI':                     'Giti',
    'Gladiator':                'Gladiator',
    'Gm':                       'GM',
    'GM':                       'GM',
    'Goalstar':                 'Goalstar',
    'Goform':                   'Goform',
    'Gold':                     'Gold',
    'Golden Caymont':           'Golden Caymont',
    'Golden Crown':             'Golden Crown',
    'Goldentyre':               'Goldentyre',
    'Goldline':                 'Goldline',
    'Goldstone':                'Goldstone',
    'Goldway':                  'Goldway',
    'Goodfriend':               'Goodfriend',
    'Goodride':                 'Goodride',
    'GOODRIDE':                 'Goodride',
    'Goodtyre':                 'Goodtyre',
    'Goodwill':                 'Goodwill',
    'Goodyear':                 'Goodyear',
    'GOODYEAR':                 'Goodyear',
    'goodyear':                 'Goodyear',
    'Grandpeak':                'Grandpeak',
    'Grandstone':               'Grandstone',
    'Great Wall':               'Great Wall',
    'Greckster':                'Greckster',
    'Green':                    'Green',
    'Green Filter':             'Green Filter',
    'Greencool':                'Greencool',
    'Greentrac':                'Greentrac',
    'Greforce':                 'Greforce',
    'Gremax':                   'Gremax',
    'Grenlander':               'Grenlander',
    'Gripmax':                  'Gripmax',
    'Gt Radial':                'GT Radial',
    'GT Radial':                'GT Radial',
    'Guangda':                  'Guangda',
    'H+B Jakoparts':            'H+B Jakoparts',
    'Habilead':                 'Habilead',
    'Haida':                    'Haida',
    'Hankook':                  'Hankook',
    'HANKOOK':                  'Hankook',
    'hankook':                  'Hankook',
    'Haotian Filter':           'Haotian Filter',
    'Haulmax':                  'Haulmax',
    'Haval':                    'Haval',
    'Headway':                  'Headway',
    'Heidenau':                 'Heidenau',
    'Hemisphere':               'Hemisphere',
    'Hengda':                   'Hengda',
    'Hengst':                   'Hengst',
    'HENGST':                   'Hengst',
    'Hercules':                 'Hercules',
    'Hermann':                  'Hermann',
    'Herovic':                  'Herovic',
    'Hifi Filter':              'Hifi Filter',
    'Hifly':                    'Hifly',
    'HIFLY':                    'Hifly',
    'Hilo':                     'Hilo',
    'Hofer':                    'Hofer',
    'Honda':                    'Honda',
    'HONDA':                    'Honda',
    'Hongqi':                   'Hongqi',
    'Horizon':                  'Horizon',
    'Hosu':                     'Hosu',
    'Hpt':                      'HPT',
    'Hunterroad':               'Hunterroad',
    'Husky':                    'Husky',
    'Huter':                    'Huter',
    'Hvcc':                     'HVCC',
    'Hyundai':                  'Hyundai',
    'HYUNDAI':                  'Hyundai',
    'Hyundai Mobis':            'Hyundai Mobis',
    'Hyundai Xteer':            'Hyundai Xteer',
    'Hyundai,Kia':              'Hyundai/Kia',   
    'Hyundai-Kia':              'Hyundai/Kia',  
    'Hyundai/Kia':              'Hyundai/Kia',
    'Ibm':                      'IBM',
    'Icon':                     'Icon',
    'Idemitsu':                 'Idemitsu',
    'IDEMITSU':                 'Idemitsu',
    'Ikon':                     'Ikon Tyres',
    'Ikon Tyres':               'Ikon Tyres',
    'Ikon Tyres (Nokian)':      'Ikon Tyres',   
    'Ilink':                    'Ilink',
    'Imperial':                 'Imperial',
    'Infimax':                  'Infimax',
    'Infinity':                 'Infinity',
    'Insa Turbo':               'Insa Turbo',
    'Interco':                  'Interco',
    'Interparts':               'Interparts',
    'Interstate':               'Interstate',
    'Invovic':                  'Invovic',
    'Ironman':                  'Ironman',
    'Isuzu':                    'Isuzu',
    'Ixat':                     'Ixat',
    'Jac':                      'JAC',
    'JAC':                      'JAC',
    'Jaderock':                 'Jaderock',
    'Japanparts':               'Japanparts',
    'Jcb':                      'JCB',
    'Jet':                      'Jet',
    "Jet!":                     'Jet',
    'Jetzon':                   'Jetzon',
    'Jhf':                      'JHF',
    'Jilutong':                 'Jilutong',
    'Jintongda':                'Jintongda',
    'Jinyu':                    'Jinyu',
    'JINYU':                    'Jinyu',
    'Jinzhongwang':             'Jinzhongwang',
    'John Deere':               'John Deere',
    'Jorden':                   'Jorden',
    'Joyroad':                  'Joyroad',
    'Jp Group':                 'JP Group',
    'Js':                       'JS',
    'Js Asakashi':              'JS Asakashi',
    'Jusbest':                  'Jusbest',
    'Just Drive':               'Just Drive',
    'K-Ex':                     'K-Ex',
    'Kainar':                   'Kainar',
    'Kama':                     'Kama',
    'KAMA':                     'Kama',
    'Кама':                     'Kama',
    'Кама-218':                 'Kama',
    'Кама-503':                 'Kama',
    'Кама-505':                 'Kama',
    'Kamali':                   'Kamali',
    'Kamaz':                    'Kamaz',
    'Камаз':                    'Kamaz',
    'Камако':                   'Kamako',
    'Kang Wang':                'Kang Wang',
    'Kansler':                  'Kansler',
    'Kapsen':                   'Kapsen',
    'KAPSEN':                   'Kapsen',
    'Kaytoon':                  'Kaytoon',
    'Kebek':                    'Kebek',
    'Kelly':                    'Kelly',
    'KELLY':                    'Kelly',
    'Kenda':                    'Kenda',
    'KENDA':                    'Kenda',
    'Kenex':                    'Kenex',
    'Kexkorea':                 'Kexkorea',
    'Kinforest':                'Kinforest',
    'King':                     'King',
    'King Meiler':              'King Meiler',
    'Kingboss':                 'Kingboss',
    'Kingstar':                 'Kingstar',
    'Kingwonder':               'Kingwonder',
    'Kixx':                     'Kixx',
    'Kleber':                   'Kleber',
    'KLEBER':                   'Kleber',
    'Klf Automotive':           'KLF Automotive',
    'Knecht':                   'Knecht',
    'Kolbenschmidt':            'Kolbenschmidt',
    'Kormoran':                 'Kormoran',
    'KORMORAN':                 'Kormoran',
    'Korparts':                 'Korparts',
    'Korson':                   'Korson',
    'Koyoroki':                 'Koyoroki',
    'Kpatos':                   'Kpatos',
    'Krauf':                    'Krauf',
    'Kumho':                    'Kumho',
    'KUMHO':                    'Kumho',
    'kumho':                    'Kumho',
    'Kunlun':                   'Kunlun',
    'Lakesea':                  'Lakesea',
    'Lande':                    'Lande',
    'Landsail':                 'Landsail',
    'Landspider':               'Landspider',
    'Lanvigator':               'Lanvigator',
    'Lassa':                    'Lassa',
    'LASSA':                    'Lassa',
    'Laufenn':                  'Laufenn',
    'LAUFENN':                  'Laufenn',
    'Lavr':                     'Lavr',
    'LAVR':                     'Lavr',
    'Lcivecht':                 'Lcivecht',
    'Leao':                     'Leao',
    'Leao Tire':                'Leao',   
    'Leapmotor':                'Leapmotor',
    'Lenso':                    'Lenso',
    'Leon':                     'Leon',
    'Li Auto':                  'Li Auto',
    'Li Ya':                    'Li Ya',
    'Linglong':                 'Linglong',
    'LINGLONG':                 'Linglong',
    'Liqui Moly':               'Liqui Moly',
    'LIQUI MOLY':               'Liqui Moly',
    'LIQUIMOLY':                'Liqui Moly',
    'liqui moly':               'Liqui Moly',
    'Liugong':                  'Liugong',
    'Long March':               'Long March',
    'Lukoil':                   'Lukoil',
    'LUKOIL':                   'Lukoil',
    'ЛУКОЙЛ':                   'Lukoil',
    'Luxxan':                   'Luxxan',
    'Lykmc':                    'Lykmc',
    'Lynk & Co':                'Lynk & Co',
    'Lynx':                     'Lynx',
    'Lynxauto':                 'Lynxauto',
    'M-Filter':                 'M-Filter',
    'Mfilter':                  'M-Filter',   
    'MFILTER':                  'M-Filter',
    'Mabor':                    'Mabor',
    'Magnum':                   'Magnum',
    'Mahle':                    'Mahle',
    'MAHLE':                    'Mahle',
    'Malatesta':                'Malatesta',
    'Maloya':                   'Maloya',
    'Mando':                    'Mando',
    'Mandokorea':               'Mando',
    'Mann':                     'Mann-Filter',
    'Mann-Filter':              'Mann-Filter',
    'MANN-FILTER':              'Mann-Filter',
    'Mann-Filter (China)':      'Mann-Filter',
    'Mannol':                   'Mannol',
    'MANNOL':                   'Mannol',
    'Marangoni':                'Marangoni',
    'Marcher':                  'Marcher',
    'Marshal':                  'Marshal',
    'MARSHAL':                  'Marshal',
    'Massimo':                  'Massimo',
    'Mastercraft':              'Mastercraft',
    'Mastersteel':              'Mastersteel',
    'Masuma':                   'Masuma',
    'Matador':                  'Matador',
    'MATADOR':                  'Matador',
    'Матадор':                  'Matador',
    'Max':                      'Max',
    'Max; Carleo':              'Max',   
    'Maxtrek':                  'Maxtrek',
    'Maxxis':                   'Maxxis',
    'MAXXIS':                   'Maxxis',
    'Mayrun':                   'Mayrun',
    'Mazda':                    'Mazda',
    'MAZDA':                    'Mazda',
    'Mazzini':                  'Mazzini',
    'Mecafilter':               'Mecafilter',
    'Medeo':                    'Medeo',
    'Meguin':                   'Meguin',
    'MEGUIN':                   'Meguin',
    'Meillor':                  'Meillor',
    'Membat':                   'Membat',
    'Mentor':                   'Mentor',
    'Mercedes-Benz':            'Mercedes-Benz',
    'MERCEDES-BENZ':            'Mercedes-Benz',
    'Merit':                    'Merit',
    'Metaco':                   'Metaco',
    'Meteor':                   'Meteor',
    'Metzeler':                 'Metzeler',
    'Meyle':                    'Meyle',
    'MEYLE':                    'Meyle',
    'Michelin':                 'Michelin',
    'MICHELIN':                 'Michelin',
    'michelin':                 'Michelin',
    'Mickey Thompson':          'Mickey Thompson',
    'Micro':                    'Micro',
    'Micronic Filter':          'Micronic Filter',
    'Mileking':                 'Mileking',
    'Miles':                    'Miles',
    'Milestone':                'Milestone',
    'Milever':                  'Milever',
    'Minerva':                  'Minerva',
    'MINERVA':                  'Minerva',
    'Mirage':                   'Mirage',
    'Mitas':                    'Mitas',
    'Mitasu':                   'Mitasu',
    'MITASU':                   'Mitasu',
    'Mitsubishi':               'Mitsubishi',
    'MITSUBISHI':               'Mitsubishi',
    'Mitsuboshi':               'Mitsuboshi',
    'Mitsuji':                  'Mitsuji',
    'Mj':                       'MJ',
    'Mobil':                    'Mobil',
    'MOBIL':                    'Mobil',
    'mobil':                    'Mobil',
    'Mobiparts':                'Mobiparts',
    'Mopar':                    'Mopar',
    'Motomaster':               'Motomaster',
    'Motorcraft':               'Motorcraft',
    'Motul':                    'Motul',
    'MOTUL':                    'Motul',
    'Mountain':                 'Mountain',
    'Mrf':                      'MRF',
    'MRF':                      'MRF',
    'Mrl':                      'MRL',
    'Mrt':                      'MRT',
    'Multi-Mile':               'Multi-Mile',
    'Naf':                      'NAF',
    'Nankang':                  'Nankang',
    'NANKANG':                  'Nankang',
    'National':                 'National',
    'Nereus':                   'Nereus',
    'Nerues':                   'Nereus',   
    'Neumaster':                'Neumaster',
    'Neuton':                   'Neuton',
    'New Power':                'New Power',
    'Nexen':                    'Nexen',
    'NEXEN':                    'Nexen',
    'Next':                     'Next',
    'Next Tread':               'Next Tread',
    'Ngn':                      'NGN',
    'Ni-Pon':                   'Ni-Pon',
    'Nio':                      'NIO',
    'Nissan':                   'Nissan',
    'NISSAN':                   'Nissan',
    'Nitto':                    'Nitto',
    'NITTO':                    'Nitto',
    'Nokian':                   'Nokian',
    'NOKIAN':                   'Nokian',
    'nokian':                   'Nokian',
    'Nokian Tyres':             'Nokian',  
    'Nokian Tyres Finland':     'Nokian',  
    'Nor-Bi':                   'Nor-Bi',
    'Nordman':                  'Nordman',
    'NORDMAN':                  'Nordman',
    'Normaks':                  'Normaks',
    'Nortec':                   'Nortec',
    'Novex':                    'Novex',
    'Nty':                      'NTY',
    "O'Green":                  'Ogreen',
    'Ogreen':                   'Ogreen',
    'Odyking':                  'Odyking',
    'Oem':                      None,   
    'OEM':                      None,
    'Oilright':                 'Oilright',
    'OILRIGHT':                 'Oilright',
    'Olymp':                    'Olymp',
    'Onnuri':                   'Onnuri',
    'Onyx':                     'Onyx',
    'Onyx Tires':               'Onyx',
    'Orium':                    'Orium',
    'Oscar':                    'Oscar',
    'Ossca':                    'Ossca',
    'Otani':                    'Otani',
    'Ovation':                  'Ovation',
    'Pace':                     'Pace',
    'Part':                     None,   
    'Part-One':                 'Part-One',
    'Parts-Mall':               'Parts-Mall',
    'Patron':                   'Patron',
    'PATRON':                   'Patron',
    'Paxaro':                   'Paxaro',
    'Pekar':                    'Pekar',
    'Pemco':                    'Pemco',
    'Petlas':                   'Petlas',
    'PETLAS':                   'Petlas',
    'Petro-Canada':             'Petro-Canada',
    'Petronas':                 'Petronas',
    'PETRONAS':                 'Petronas',
    'Pexol':                    'Pexol',
    'Phg':                      'PHG',
    'Pilenga':                  'Pilenga',
    'PILENGA':                  'Pilenga',
    'Pirelli':                  'Pirelli',
    'PIRELLI':                  'Pirelli',
    'pirelli':                  'Pirelli',
    'Pitbull':                  'Pitbull',
    'Platin':                   'Platin',
    'Pneumant':                 'Pneumant',
    'Point S':                  'Point S',
    'Polo':                     'Polo',
    'Porwing':                  'Porwing',
    'Power':                    'Power',
    'Powertrac':                'Powertrac',
    'POWERTRAC':                'Powertrac',
    'Powertrack':               'Powertrac',   
    'Predator':                 'Predator',
    'Premiorri':                'Premiorri',
    'Premium':                  'Premium',
    'Presa':                    'Presa',
    'Primewell':                'Primewell',
    'Pro Comp':                 'Pro Comp',
    'Profix':                   'Profix',
    'Protec':                   'Protec',
    'Purflux':                  'Purflux',
    'Qlife':                    'Qlife',
    'Racer':                    'Racer',
    'Radar':                    'Radar',
    'Raider':                   'Raider',
    'Rameder':                  'Rameder',
    'Rapid':                    'Rapid',
    'RAPID':                    'Rapid',
    'Ravenol':                  'Ravenol',
    'RAVENOL':                  'Ravenol',
    'Rb-Exide':                 'RB-Exide',
    'Regal':                    'Regal',
    'Remington':                'Remington',
    'Renault':                  'Renault',
    'RENAULT':                  'Renault',
    'Replica':                  'Replica',
    'Riken':                    'Riken',
    'RIKEN':                    'Riken',
    'Riostone':                 'Riostone',
    'Ritar':                    'Ritar',
    'Roadbuster':               'Roadbuster',
    'Roadclaw':                 'Roadclaw',
    'Roadcruza':                'Roadcruza',
    'Roadguider':               'Roadguider',
    'Roadhiker':                'Roadhiker',
    'Roadking':                 'Roadking',
    'Roadmarch':                'Roadmarch',
    'Roador':                   'Roador',
    'Roadshine':                'Roadshine',
    'Roadstar':                 'Roadstar',
    'Roadstone':                'Roadstone',
    'ROADSTONE':                'Roadstone',
    'Roadx':                    'Roadx',
    'Robot Coupe':              'Robot Coupe',
    'Rockbuster':               'Rockbuster',
    'Rocket':                   'Rocket',
    'Rockstone':                'Rockstone',
    'Rolf':                     'Rolf',
    'ROLF':                     'Rolf',
    'Rosava':                   'Rosava',
    'Росава':                   'Rosava',
    'Rosneft':                  'Rosneft',
    'ROSNEFT':                  'Rosneft',
    'РОСНЕФТЬ':                 'Rosneft',
    'Роснефть':                 'Rosneft',
    'Rotalla':                  'Rotalla',
    'ROTALLA':                  'Rotalla',
    'Rotex':                    'Rotex',
    'Routeway':                 'Routeway',
    'Rovelo':                   'Rovelo',
    'Rowe':                     'Rowe',
    'ROWE':                     'Rowe',
    'Roxxis':                   'Roxxis',
    'Royal Black':              'Royal Black',
    'Rydanz':                   'Rydanz',
    'S&K':                      'S&K',
    'S-Oil':                    'S-Oil',
    'Safecess':                 'Safecess',
    'Saferich':                 'Saferich',
    'Sagitar':                  'Sagitar',
    'Sailun':                   'Sailun',
    'SAILUN':                   'Sailun',
    'Sakura':                   'Sakura',
    'Sampa':                    'Sampa',
    'Sampiyon':                 'Sampiyon',
    'Samson':                   'Samson',
    'Saonlal':                  'Saonlal',
    'Sap':                      'SAP',
    'Sat':                      'SAT',
    'Sata':                     'Sata',
    'Satoya':                   'Satoya',
    'Sava':                     'Sava',
    'SAVA':                     'Sava',
    'Saxon':                    'Saxon',
    'Scope':                    'Scope',
    'Scorpion':                 'Scorpion',
    'Sct':                      'SCT',
    'Semperit':                 'Semperit',
    'SEMPERIT':                 'Semperit',
    'Sentury':                  'Sentury',
    'Set Parts':                'Set Parts',
    'Sf-Filter':                'SF-Filter',
    'Sh':                       'SH',
    'Shacman':                  'Shacman',
    'Sheft':                    'Sheft',
    'Shell':                    'Shell',
    'SHELL':                    'Shell',
    'Shell Helix':              'Shell Helix',
    'SHELL HELIX':              'Shell Helix',
    'Sheyk':                    'Sheyk',
    'Shinko':                   'Shinko',
    'Sibbear':                  'Sibbear',
    'Sicuro':                   'Sicuro',
    'Siemens':                  'Siemens',
    'Sigma':                    'Sigma',
    'Signet':                   'Signet',
    'Silverstone':              'Silverstone',
    'Sime':                     'Sime',
    'Simex':                    'Simex',
    'Sintec':                   'Sintec',
    'SINTEC':                   'Sintec',
    'Sk Encar':                 'SK Encar',
    'Solideal':                 'Solideal',
    'Sonar':                    'Sonar',
    'Sonix':                    'Sonix',
    'Sonny':                    'Sonny',
    'Sorl':                     'Sorl',
    'Speedmate':                'Speedmate',
    'Speedways':                'Speedways',
    'Sportiva':                 'Sportiva',
    'Sportrak':                 'Sportrak',
    'Sportway':                 'Sportway',
    'Sputnik':                  'Sputnik',
    'Srr':                      'SRR',
    'Ssang Yong':               'SsangYong',
    'SsangYong':                'SsangYong',
    'Stal':                     'Stal',
    'STAL':                     'Stal',
    'Stampede':                 'Stampede',
    'Starco':                   'Starco',
    'Starfire':                 'Starfire',
    'Starmann':                 'Starmann',
    'Starmaxx':                 'Starmaxx',
    'STARMAXX':                 'Starmaxx',
    'Steher':                   'Steher',
    'Stellox':                  'Stellox',
    'Stihl':                    'Stihl',
    'Stone':                    'Stone',
    'Str':                      'STR',
    'Strial':                   'Strial',
    'Strub':                    'Strub',
    'Stunner':                  'Stunner',
    'Subaru':                   'Subaru',
    'SUBARU':                   'Subaru',
    'Sufix':                    'Sufix',
    'Sumitomo':                 'Sumitomo',
    'SUMITOMO':                 'Sumitomo',
    'Sumo':                     'Sumo',
    'Sumomoto':                 'Sumitomo', 
    'Sunfull':                  'Sunfull',
    'Sunitrac':                 'Sunitrac',
    'Sunny':                    'Sunny',
    'Sunstyer':                 'Sunstyer',
    'Suntek':                   'Suntek',
    'Sunwide':                  'Sunwide',
    'Super':                    'Super',
    'Super-Q':                  'Super-Q',
    'Superhawk':                'Superhawk',
    'Superia':                  'Superia',
    'SUPERIA':                  'Superia',
    'Superstone':               'Superstone',
    'Superzing':                'Superzing',
    'Suzuki':                   'Suzuki',
    'SUZUKI':                   'Suzuki',
    'Swag':                     'Swag',
    'T-Rex':                    'T-Rex',
    'Taiho':                    'Taiho',
    'Taitong':                  'Taitong',
    'Taiwan':                   'Taiwan',
    'Takayama':                 'Takayama',
    'Tamotsu':                  'Tamotsu',
    'Tatsumi':                  'Tatsumi',
    'Taurus':                   'Taurus',
    'TAURUS':                   'Taurus',
    'Taxat':                    'Taxat',
    'Tbb Tires':                'TBB Tires',
    'Tcl':                      'TCL',
    'Technic':                  'Technic',
    'Tedex':                    'Tedex',
    'Telstar':                  'Telstar',
    'Tempra':                   'Tempra',
    'Teraflex':                 'Teraflex',
    'Tercelo':                  'Tercelo',
    'Terraking':                'Terraking',
    'Tesla':                    'Tesla',
    'Tesla Technics':           'Tesla Technics',
    'Texaco':                   'Texaco',
    'TEXACO':                   'Texaco',
    'Teyko':                    'Teyko',
    'Thermo':                   'Thermo',
    'Three-A':                  'Three-A',
    'Thunderer':                'Thunderer',
    'Tianfu':                   'Tianfu',
    'Tianli':                   'Tianli',
    'Tigar':                    'Tigar',
    'TIGAR':                    'Tigar',
    'Titan':                    'Titan',
    'Toledo':                   'Toledo',
    'Tomket':                   'Tomket',
    'Top Trust':                'Top Trust',
    'Topcover':                 'Topcover',
    'Topfils':                  'Topfils',
    'Torero':                   'Torero',
    'Torero (Matador)':         'Torero',  
    'Torque':                   'Torque',
    'Totachi':                  'Totachi',
    'TOTACHI':                  'Totachi',
    'Total':                    'Total',
    'TOTAL':                    'Total',
    'total':                    'Total',
    'Total Tools':              'Total Tools',
    'Totalenergies':            'TotalEnergies',
    'TotalEnergies':            'TotalEnergies',
    'Tourador':                 'Tourador',
    'Toyo':                     'Toyo',
    'TOYO':                     'Toyo',
    'Toyoguard':                'Toyoguard',
    'Toyota':                   'Toyota',
    'TOYOTA':                   'Toyota',
    'Tracmax':                  'Tracmax',
    'TRACMAX':                  'Tracmax',
    'Trailcutter':              'Trailcutter',
    'Trans':                    'Trans',
    'Transmate':                'Transmate',
    'Transtone':                'Transtone',
    'Trayal':                   'Trayal',
    'Trazano':                  'Trazano',
    'Trelleborg':               'Trelleborg',
    'Tri-Ace':                  'Tri-Ace',
    'Triangle':                 'Triangle',
    'TRIANGLE':                 'Triangle',
    'triangle':                 'Triangle',
    'Triangle Tire':            'Triangle',  
    'Tristar':                  'Tristar',
    'TRISTAR':                  'Tristar',
    'Truefast':                 'Truefast',
    'Tsn':                      'TSN',
    'Tuneful':                  'Tuneful',
    'Tunga':                    'Tunga',
    'TUNGA':                    'Tunga',
    'Tyc':                      'TYC',
    'Tyrex':                    'Tyrex',
    'TYREX':                    'Tyrex',
    'Tysonking':                'Tysonking',
    'Tyumen':                   'Tyumen',
    'Тюменский':                'Tyumen',
    'Tzer Li':                  'Tzer Li',
    'Ufi':                      'UFI',
    'UFI':                      'UFI',
    'Uks':                      'UKS',
    'Ultra':                    'Ultra',
    'Ultra-Power':              'Ultra-Power',
    'Ultraforce':               'Ultraforce',
    'Uniglory':                 'Uniglory',
    'Unikum':                   'Unikum',
    'Union':                    'Union',
    'Uniroyal':                 'Uniroyal',
    'UNIROYAL':                 'Uniroyal',
    'United':                   'United',
    'United Motors':            'United Motors',
    'United Oil':               'United Oil',
    'Unix':                     'Unix',
    'Unox':                     'Unox',
    'Ural':                     'Ural',
    'Урал':                     'Ural',
    'Uz-Dw':                    'UZ-DW',
    'Vag':                      'VAG',
    'VAG':                      'VAG',
    'Valeo':                    'Valeo',
    'VALEO':                    'Valeo',
    'Valino':                   'Valino',
    'Valvoline':                'Valvoline',
    'VALVOLINE':                'Valvoline',
    'Varta':                    'Varta',
    'VARTA':                    'Varta',
    'Vco':                      'VCO',
    'Veerubber':                'Veerubber',
    'Venom':                    'Venom',
    'Venom Power':              'Venom Power',
    'Vglory':                   'Vglory',
    'Viatti':                   'Viatti',
    'VIATTI':                   'Viatti',
    'Vic':                      'VIC',
    'Vict Rhee Jin':            'Vict Rhee Jin',
    'Victor Reinz':             'Victor Reinz',
    'Victorun':                 'Victorun',
    'Vika':                     'Vika',
    'Viking':                   'Viking',
    'VIKING':                   'Viking',
    'Vitex':                    'Vitex',
    'VITEX':                    'Vitex',
    'Vitour':                   'Vitour',
    'Vittos':                   'Vittos',
    'Vl':                       'VL',
    'Vla':                      'VLA',
    'Vlа':                      'VLA',   
    'Volex':                    'Volex',
    'Voltyre':                  'Voltyre',
    'Волтаир':                  'Voltyre',
    'Волтайр':                  'Voltyre',
    'Волтайр-Пром':             'Voltyre',
    'Volvo':                    'Volvo',
    'VOLVO':                    'Volvo',
    'Voyah':                    'Voyah',
    'Vredestein':               'Vredestein',
    'VREDESTEIN':               'Vredestein',
    'Vsp':                      'VSP',
    'Wabco':                    'Wabco',
    'WABCO':                    'Wabco',
    'Waistone':                 'Waistone',
    'Wanda':                    'Wanda',
    'Wanderbilt':               'Wanderbilt',
    'Wanli':                    'Wanli',
    'WANLI':                    'Wanli',
    'Westlake':                 'Westlake',
    'WESTLAKE':                 'Westlake',
    'Wewatt':                   'Wewatt',
    'Wezer':                    'Wezer',
    'Wide-Walli':               'Wide-Walli',
    'Wideway':                  'Wideway',
    'Wildwolfking':             'Wildwolfking',
    'Winda':                    'Winda',
    'Windforce':                'Windforce',
    'WINDFORCE':                'Windforce',
    'Windpower':                'Windpower',
    'Wingood':                  'Wingood',
    'Winkod':                   'Winkod',
    'Winrun':                   'Winrun',
    'Wolftyres':                'Wolftyres',
    'Wonjin':                   'Wonjin',
    'Wxqp':                     'WXQP',
    'X-Oil':                    'X-Oil',
    'Xado':                     'Xado',
    'XADO':                     'Xado',
    'Xcmg':                     'XCMG',
    'Xinjiang Kunlun Tyre':     'Kunlun',   
    'Xtyre':                    'Xtyre',
    'Yacco':                    'Yacco',
    'YACCO':                    'Yacco',
    'Yamaha':                   'Yamaha',
    'Yamalube':                 'Yamalube',
    'Yartu':                    'Yartu',
    'Yatai':                    'Yatai',
    'Yatone':                   'Yatone',
    'Yellow Sea':               'Yellow Sea',
    'Yitong':                   'Yitong',
    'Yokohama':                 'Yokohama',
    'YOKOHAMA':                 'Yokohama',
    'yokohama':                 'Yokohama',
    'Yomar':                    'Yomar',
    'Young':                    'Young',
    'Ysf':                      'YSF',
    'Yume':                     'Yume',
    'Yunde':                    'Yunde',
    'Yunli':                    'Yunli',
    'Yunxin':                   'Yunxin',
    'Zeekr':                    'Zeekr',
    'Zeetex':                   'Zeetex',
    'ZEETEX':                   'Zeetex',
    'Zekkert':                  'Zekkert',
    'Zelda':                    'Zelda',
    'Zentparts':                'Zentparts',
    'Zero Milage':              'Zero Mileage',   
    'Zero Mileage':             'Zero Mileage',
    'Zeta':                     'Zeta',
    'Zeus':                     'Zeus',
    'Zf':                       'ZF',
    'ZF':                       'ZF',
    'Zhongyi':                  'Zhongyi',
    'Zic':                      'ZIC',
    'ZIC':                      'ZIC',
    'Zmax':                     'Zmax',
    'ZMAX':                     'Zmax',
    'Ztd':                      'ZTD',
    'Zubr':                     'Zubr',
    'Зубр':                     'Zubr',
    'Zuff':                     'Zuff',
    'Автомагнат':               'Avtomagnат',
    'Альфаком':                 'Alfakom',
    'Ама':                      'Ama',
    'Анвек':                    'Anvek',
    'Ашк':                      'Алтайский Шинный Комбинат',
    'Алтайский Шинный Комбинат':'Алтайский Шинный Комбинат',
    'Алтайшина':                'Алтайский Шинный Комбинат',
    'Барнаул':                  'Барнаул',
    'Барнаульский Завод Ати':   'Барнаульский Завод АТИ',
    'Барнаульский Шинный Завод':'Барнаульский Шинный Завод',
    'Барс':                     'Bars',
    'Белая Церковь':            'Белая Церковь',
    'Белла':                    'Белла',
    'Бшз':                      'Барнаульский Шинный Завод',
    'Вихрь':                    'Вихрь',
    'Вмпавто':                  'ВМПАвто',
    'Волга-Ойл':                'Волга-Ойл',
    'Воронеж':                  'Воронеж',
    'Газпромнефть':             'Gazpromneft',
    'Газпром Нефть':            'Gazpromneft',
    'Газпром':                  'Gazpromneft',
    'Днепрошина':               'Днепрошина',
    'Кама-218':                 'Kama',
    'Кама-503':                 'Kama',
    'Кама-505':                 'Kama',
    'Камако':                   'Kamako',
    'Киров':                    'Киров',
    'Костромской Фильтр':       'Костромской Фильтр',
    'Матадор':                  'Matador',
    'Медведь':                  'Медведь',
    'Москва':                   'Москва',
    'Нижнекамский Шинный Завод':'Нижнекамский Шинный Завод',
    'Нижнекамскшина':           'Нижнекамский Шинный Завод',
    'Ниишп':                    'НИИШП',
    'Омск':                     'Омск',
    'Омский':                   'Омский Шинный Завод',
    'Омский Шинный Завод':      'Омский Шинный Завод',
    'Омскшина':                 'Омский Шинный Завод',
    'Петрошина':                'Петрошина',
    'Россия':                   None,   
    'Сибур':                    'Сибур',
    'Стартвольт':               'Стартвольт',
    'Тракт':                    'Тракт',
    'Уаз':                      'УАЗ',
    'Электра':                  'Электра',
    'Элемент':                  'Элемент',
    'Язда':                     'ЯЗДА',
    'Ярославль':                'Ярославский Шинный Завод',
    'Ярославский':              'Ярославский Шинный Завод',
    'Ярославский Шинный Завод': 'Ярославский Шинный Завод',
    'Яшз':                      'Ярославский Шинный Завод',
}
 

_JUNK_RE = re.compile(
    r'^(\d+[\./]\d+R\d|R\d{2}$|\d+Pr$|Рц-\d|[ХЦ]\d)',
    re.IGNORECASE,
)
 
 
def clean_brand(brand, brand_dict: dict = BRAND_DICT) -> Optional[str]:
    if not isinstance(brand, str) or not brand.strip():
        return None
 
    b = brand.strip()
 
    if b in brand_dict:
        return brand_dict[b]          
 
    b_lower = b.lower()
    for k, v in brand_dict.items():
        if isinstance(k, str) and k.lower() == b_lower:
            return v
 
    if _JUNK_RE.search(b):
        return None
 
    for sep in (';', '/', ','):
        if sep in b:
            first = b.split(sep)[0].strip()
            if first and first != b:
                return clean_brand(first, brand_dict)
    return b
 


def normalize_availability(val: str) -> Optional[str]:
    if not isinstance(val, str):
        return None
    v = val.strip().lower()
    if v in ('в наличии', 'instock', 'in_stock', 'есть'):
        return 'in_stock'
    if v in ('под заказ', 'out_of_stock', 'нет в наличии', 'нет'):
        return 'out_of_stock'
    return None


def clean_price(val) -> Optional[float]:
    try:
        p = float(val)
        return p if p > 0 else None
    except (TypeError, ValueError):
        return None



def normalize_bool(val) -> Optional[bool]:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ('true', 'да', 'есть', '1'):
            return True
        if v in ('false', 'нет', '0'):
            return False
    return None


SEASON_MAP = {
    'летняя': 'summer', 'летние шины': 'summer', 'летние': 'summer',
    'зимняя': 'winter', 'зимние шины': 'winter', 'зимние': 'winter',
    'зимние нешипованные шины': 'winter', 'зимние шипованные шины': 'winter',
    'зимние шины под шип': 'winter',
    'всесезонная': 'all_season', 'всесезонные шины': 'all_season',
    'всесезонные': 'all_season',
    'summer': 'summer', 'winter': 'winter',
    'allseason': 'all_season', 'all_season': 'all_season',
}


def normalize_season(val: str) -> Optional[str]:
    if not isinstance(val, str):
        return None
    return SEASON_MAP.get(val.strip().lower())


def normalize_diameter(val) -> Optional[float]:
    if pd.isna(val):
        return None
    s = str(val).strip().upper().lstrip('R').rstrip('"').rstrip("'")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_speed_index(val: str) -> Optional[str]:
    if not isinstance(val, str):
        return None
    v = val.strip().replace('Н', 'H').replace('Т', 'T')
    v = re.sub(r'\s+XL$', ' XL', v, flags=re.IGNORECASE)
    return v.strip().upper() if v else None


VISCOSITY_RE = re.compile(
    r'(\d{1,2}W[-–\s]?\d{1,2}|\d{1,2}W|\bSAE\s*\d+\w*)', re.IGNORECASE
)

def normalize_viscosity(val: str) -> Optional[str]:
    """'5W30' / '5w-30' / '5W 30' → '5W-30'. Берём первое если через ';'."""
    if not isinstance(val, str):
        return None
    val = val.split(';')[0].strip()
    if val.lower() in ('отсутствует', ''):
        return None
    m = VISCOSITY_RE.search(val)
    if m:
        v = m.group(0).upper().replace('–', '-').replace(' ', '')
        v = re.sub(r'(\d+W)(\d+)', r'\1-\2', v)
        return v
    return val.strip() or None


def normalize_volume(val) -> Optional[float]:
    """'5 л' / '400 мл' / 5.0 → float литры."""
    if pd.isna(val):
        return None
    s = str(val).strip().lower()
    m = re.search(r'([\d.,]+)\s*мл', s)
    if m:
        return round(float(m.group(1).replace(',', '.')) / 1000, 3)
    m = re.search(r'([\d.,]+)\s*(л|l|литр)', s)
    if m:
        return float(m.group(1).replace(',', '.'))
    try:
        return float(s)
    except ValueError:
        return None


OIL_TYPE_MAP = {
    'синтетическое': 'synthetic', 'синтетика': 'synthetic', 'synthetic': 'synthetic',
    'полусинтетическое': 'semi-synthetic', 'полусинтетика': 'semi-synthetic',
    'минеральное': 'mineral', 'mineral': 'mineral',
    'гидрокрекинговое': 'hydrocracking',
    'масло для двигателя': None,
}


def normalize_oil_type(val: str) -> Optional[str]:
    if not isinstance(val, str):
        return None
    v = val.split(';')[0].strip().lower()
    return OIL_TYPE_MAP.get(v, v if v else None)


ENGINE_TYPE_NORM = {
    'бензиновый': 'gasoline', 'gasoline': 'gasoline',
    'дизельный': 'diesel', 'diesel': 'diesel',
    'турбированный': 'turbocharged',
    'все типы': 'universal', 'универсальное': 'universal',
    'бензиновые и дизельные': 'gasoline/diesel',
    'дизельный/турбодизельный': 'diesel/turbodiesel',
    '4t': '4-stroke', 'четырехтактный': '4-stroke',
    'двухтактный': '2-stroke',
    'газовый': 'gas',
}


def normalize_engine_type(val: str) -> Optional[str]:
    if not isinstance(val, str):
        return None
    parts = [p.strip().lower() for p in re.split(r'[;/,]', val)]
    normed = []
    for p in parts:
        n = ENGINE_TYPE_NORM.get(p)
        if n and n not in normed:
            normed.append(n)
    return '/'.join(normed) if normed else val.strip()







RENAME_ALMATYERS = {
    'Производитель':               'brand',
    'images':                      'image_url',
    'Назначение':                  'vehicle_type',
    'Ширина шины':                 'width(mm)',
    'Высота профиля шины':         'profile_height(%)',
    'Посадочный диаметр шины':     'rim_diameter',
    'Индекс нагрузки шины':        'load_index',
    'Сезонность шин':              'season',
    'Индекс скорости':             'speed_index',
    'Модель':                      'model',
    'Страна производитель':        'brand_country',
    'Тип':                         'tire_type',
    'Диаметр шины':              'tire_diameter',

    'Состояние': 'condition',
    'Вид шины': 'tire_construction_type',
    'Полнопрофильная шина': 'is_full_profile',
    'Шина с повышенной нагрузкой': 'is_reinforced',
    'Шина с защитой обода диска': 'has_rim_protection',
    'Сцепление на мокрой поверхности': 'wet_grip',
    'Марка': 'compatible_vehicle_brand',
    'Безопасная шина': 'runflat',
    'Диаметр колеса/диска': 'wheel_rim_diameter',
    'Тип шины для спецтехники': 'special_equipment_tire_type',
    'Ось': 'axle_position',
    'Динамическая окружность прокатки': 'dynamic_rolling_circumference',
    'Наружный диаметр': 'outer_diameter',
    'Статический радиус нагрузки': 'static_load_radius',
    'Ширина сечения': 'section_width',
    'Допустимый обод': 'approved_rim',
    'Норма слойности': 'ply_rating',
    'Предназначение': 'wheel_position',
    'Рекомендуемый диск': 'recommended_rim',
    'Тип протектора по TRA': 'tread_type_tra',
    'Типоразмер': 'tire_size',

    'Ширина': 'width_numeric',
    'Внешний диаметр': 'outer_diameter_mm',
    'Ширина секции': 'section_width_mm',
    'Статический заряженный радиус': 'static_loaded_radius',
    'Окружность динамического вращения': 'dynamic_rolling_circumference_mm',
    'Радиус статической нагрузки': 'static_load_radius_mm',
    'Ширина профиля': 'section_width_profile_mm',
    'Радиус профиля': 'profile_radius',
    'Рабочее давление': 'inflation_pressure',
    'Максимальная нагрузка на шину': 'max_load_per_tire',
    'Штрихкод': 'barcode',

    'Посадочный диаметр камеры': 'tube_rim_diameter',
    'Совместимость с моделью': 'compatible_model',
    'Тип техники': 'equipment_type',
    'Ширина камеры': 'tube_width',
    'Динамический радиус': 'dynamic_radius',
    'Глубина рисунка протектора': 'tread_depth',

    'Индекс нагрузки (ведущее колесо)': 'load_index_drive_axle',
    'Индекс нагрузки (свободное качение)': 'load_index_free_rolling',
    'Индекс нагрузки (с двумя осями)': 'load_index_dual_axle',
    'Индекс нагрузки (с одной осью)': 'load_index_single_axle',

    'Длина внутренней полуокружности плоскосложенной камеры, мм': 'flat_tube_half_circumference_mm',
    'Ширина плоскосложенной камеры, мм': 'flat_tube_width_mm',

    'Уровень шума шин': 'noise_level_db',
    'Наружный диаметр шины': 'outer_diameter_inches',
    'Топливная эффективность шин': 'fuel_efficiency',
    'Материал': 'material',
}

RENAME_FDRIVE_TYRES = {
    'product_id':           'product_id',  
    'images':               'image_url',
    'tyre_auto_type_name':  'vehicle_type',
    'width':                'width(mm)',
    'height':               'profile_height(%)',
    'diameter':             'rim_diameter',
    'velocity_index':       'speed_index',
    'tyre_stud_type_name':  'stud_type',
}

RENAME_CARCITY = {
    'source_product_id':    'product_id',
    'source_url':           'url',
    'tire_width':           'width(mm)',
    'tire_profile':         'profile_height(%)',
    'tire_diameter':        'rim_diameter',
    'load_index':           'load_index',
    'studded':              'stud_type',
    'model_name':           'model',
}

RENAME_PITSTOPSHOP = {
    'source_product_id':    'product_id',
    'source_url':           'url',
    'tire_width':           'width(mm)',
    'tire_profile':         'profile_height(%)',
    'tire_diameter':        'rim_diameter',
    'load_index':           'load_index',
    'studded':              'stud_type',
    'model_name':           'model',
    # 'category_l1':          'category_group',
    'brand_country':   'manufacture_country',
    'car_type': 'vehicle_type',
}

RENAME_SATU = {
    'source_product_id':    'product_id',
    'source_url':           'url',
    'product_name':         'name',
    'image_urls':           'image_url',
    'width':                'width(mm)',
    'profile':              'profile_height(%)',
    'diameter':             'rim_diameter',
    'load_index':           'load_index',
}

RENAME_FORTE = {
    'source_product_id':    'product_id',
    'source_url':           'url',
    'product_name':         'name',
    'image_urls':           'image_url',
    'width':                'width(mm)',
    'profile':              'profile_height(%)',
    'diameter':             'rim_diameter',
    'load_index':           'load_index',
}




def clean_carcity(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    drop_cols = ['oem_numbers', 'city', 'compatible_brand',
                 'compatible_model', 'compatible_years', 'delivery_days']
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True)

    df.rename(columns={k: v for k, v in RENAME_CARCITY.items() if k in df.columns}, inplace=True)

    df = drop_empty_columns(df)
    df = drop_duplicates(df, 'carcity_products')


    df['normalized_name']  = df['name'].apply(normalized_name)   
    df['parsed_at'] = pd.to_datetime(df['parsed_at'], errors='coerce')
    df['parsed_date'] = df['parsed_at'].dt.date
    df['parsed_time'] = df['parsed_at'].dt.strftime('%H:%M:%S')
    df.drop(columns=['parsed_at'], inplace=True)
    category_map = {
    'tires': 'Шины',
    'oils': 'Моторные масла',
    'filters': 'Фильтры',
    'batteries': 'Аккумуляторы'
    }
    df['category_group'] = df['category_group'].map(category_map)
    df['brand']            = df['brand'].apply(lambda x: clean_brand(x, BRAND_DICT))
    df['price']            = df['price'].apply(clean_price)
    df['availability']     = df['availability'].apply(normalize_availability)
    df['season']           = df['season'].apply(normalize_season)
    df['rim_diameter']     = df['rim_diameter'].apply(normalize_diameter) if 'rim_diameter' in df.columns else None
    df['speed_index']      = df['speed_index'].apply(normalize_speed_index) if 'speed_index' in df.columns else None
    df['runflat']          = df['runflat'].apply(normalize_bool) if 'runflat' in df.columns else None
    df['stud_type']        = df['stud_type'].apply(normalize_bool) if 'stud_type' in df.columns else None
    df['viscosity']        = df['viscosity'].apply(normalize_viscosity) if 'viscosity' in df.columns else None
    df['volume_liters']    = df['volume_liters'].apply(normalize_volume) if 'volume_liters' in df.columns else None
    df['oil_type']         = df['oil_type'].apply(normalize_oil_type) if 'oil_type' in df.columns else None
    df['engine_type']      = df['engine_type'].apply(normalize_engine_type) if 'engine_type' in df.columns else None
    if 'tread_pattern' in df.columns:
        df['tread_pattern'] = df['tread_pattern'].apply(
            lambda x: normalize_bool(x) if isinstance(x, str) and x.lower() in ('true', 'false') else x
        )
    if 'hypoid' in df.columns:
        df['hypoid'] = df['hypoid'].apply(normalize_bool)
    return df


def clean_pitstopshop(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df = df.drop(columns=['category_group', 'seller_name'], axis=1)
    df.rename(columns={k: v for k, v in RENAME_PITSTOPSHOP.items() if k in df.columns}, inplace=True)

    if 'tire_type' in df.columns:
        df.rename(columns={'tire_type': 'vehicle_type'}, inplace=True)
    if 'category_l1' in df.columns:
        df.rename(columns={'category_l1': 'category_group'}, inplace=True)

    df = drop_empty_columns(df)
    df = drop_duplicates(df, 'pitstopshop_products')

    df['source']          = 'PitStopShop'
    df['normalized_name'] = df['name'].apply(normalized_name)
    df['parsed_at'] = pd.to_datetime(df['parsed_at'], errors='coerce')
    df['parsed_date'] = df['parsed_at'].dt.date
    df['parsed_time'] = df['parsed_at'].dt.strftime('%H:%M:%S')
    df.drop(columns=['parsed_at'], inplace=True)
    df['brand']           = df['brand'].apply(lambda x: clean_brand(x, BRAND_DICT))
    df['price']           = df['price'].apply(clean_price)
    df['availability']    = df['availability'].apply(normalize_availability)
    df['season']          = df['season'].apply(normalize_season)
    df['rim_diameter']    = df['rim_diameter'].apply(normalize_diameter) if 'rim_diameter' in df.columns else None
    df['speed_index']     = df['speed_index'].apply(normalize_speed_index) if 'speed_index' in df.columns else None
    df['runflat']         = df['runflat'].apply(normalize_bool) if 'runflat' in df.columns else None
    df['stud_type']       = df['stud_type'].apply(normalize_bool) if 'stud_type' in df.columns else None
    return df


def clean_almatyers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if 'category' in df.columns:
        cat_parts = df['category'].str.split('>', expand=True)
        df['source']        = cat_parts[0].str.strip() if 0 in cat_parts.columns else None
        df['category_group']= 'Шины'
        df['category_l1'] = cat_parts[1].str.strip() if 1 in cat_parts.columns else None
        df['category_leaf'] = cat_parts[2].str.strip() if 2 in cat_parts.columns else None

    df.rename(columns={k: v for k, v in RENAME_ALMATYERS.items() if k in df.columns}, inplace=True)

    df = df.drop(columns =['title'], errors='ignore')  

    df = drop_empty_columns(df)
    df = drop_duplicates(df, 'almatyres_products')

    df['normalized_name'] = df['name'].apply(normalized_name) if 'name' in df.columns else None
    df['brand']           = df['brand'].apply(lambda x: clean_brand(x, BRAND_DICT)) if 'brand' in df.columns else None
    df['price']           = df['price'].apply(clean_price) if 'price' in df.columns else None
    df['availability']    = df['availability'].apply(normalize_availability) if 'availability' in df.columns else None
    df['season']          = df['season'].apply(normalize_season) if 'season' in df.columns else None
    df['speed_index']     = df['speed_index'].apply(normalize_speed_index) if 'speed_index' in df.columns else None
    if 'rim_diameter' in df.columns:
        df['rim_diameter'] = df['rim_diameter'].apply(normalize_diameter)
    if 'reinforced' in df.columns:
        df['reinforced'] = df['reinforced'].apply(normalize_bool)
    df['source_site'] = 'almatyers'
    return df


def clean_satu(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    drop_cols = ['sku_id', 'source_uid', 'normalized_name', 'old_price']
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True)

    df.rename(columns={k: v for k, v in RENAME_SATU.items() if k in df.columns}, inplace=True)
        
    if 'category' in df.columns:
        df.rename(columns={'category': 'category_leaf'}, inplace=True)

    df = drop_empty_columns(df)
    df = drop_duplicates(df, 'satu_products')

    df['normalized_name'] = df['name'].apply(normalized_name)
    df['brand']           = df['brand'].apply(lambda x: clean_brand(x, BRAND_DICT))
    df['price']           = df['price'].apply(clean_price)
    df['parsed_at'] = pd.to_datetime(df['parsed_at'], errors='coerce')
    df['parsed_date'] = df['parsed_at'].dt.date
    df['parsed_time'] = df['parsed_at'].dt.strftime('%H:%M:%S')
    df.drop(columns=['parsed_at'], inplace=True)
    df['availability']    = df['availability'].apply(normalize_availability)
    df['season']          = df['season'].apply(normalize_season) if 'season' in df.columns else None
    df['viscosity']       = df['viscosity'].apply(normalize_viscosity) if 'viscosity' in df.columns else None
    df['volume_liters']   = df['volume_liters'].apply(normalize_volume) if 'volume_liters' in df.columns else None
    df['oil_type']        = df['oil_type'].apply(normalize_oil_type) if 'oil_type' in df.columns else None
    df['engine_type']     = df['engine_type'].apply(normalize_engine_type) if 'engine_type' in df.columns else None
    if 'speed_index' in df.columns:
        df['speed_index'] = df['speed_index'].apply(
            lambda x: normalize_speed_index(str(x).split(';')[0]) if pd.notna(x) else None
        )
    if 'rim_diameter' in df.columns:
        df['rim_diameter'] = df['rim_diameter'].apply(normalize_diameter)
    if 'filter_type' in df.columns:
        df['filter_type'] = df['filter_type'].apply(
            lambda x: str(x).split(';')[0].strip() if pd.notna(x) else None
        )
    return df
    


def clean_forte(df: pd.DataFrame) -> pd.DataFrame:
    """Forte: та же структура что satu."""
    df = df.copy()

    drop_cols = ['sku_id', 'source_uid', 'normalized_name']
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True)

    df.rename(columns={k: v for k, v in RENAME_FORTE.items() if k in df.columns}, inplace=True)

    if 'category' in df.columns:
        df.rename(columns={'category': 'category_group'}, inplace=True)

    df = drop_empty_columns(df)
    df = drop_duplicates(df, 'forte_products')

    df['normalized_name'] = df['name'].apply(normalized_name)
    df['brand']           = df['brand'].apply(lambda x: clean_brand(x, BRAND_DICT))
    df['price']           = df['price'].apply(clean_price)
    df['availability']    = df['availability'].apply(normalize_availability)
    df['season']          = df['season'].apply(normalize_season) if 'season' in df.columns else None
    df['viscosity']       = df['viscosity'].apply(normalize_viscosity) if 'viscosity' in df.columns else None
    df['oil_type']        = df['oil_type'].apply(normalize_oil_type) if 'oil_type' in df.columns else None
    df['volume_liters']    = df['volume_liters'].apply(normalize_volume) if 'volume_liters' in df.columns else None
    df['engine_type']     = df['engine_type'].apply(normalize_engine_type) if 'engine_type' in df.columns else None
    df['runflat']         = df['runflat'].apply(normalize_bool) if 'runflat' in df.columns else None
    if 'rim_diameter' in df.columns:
        df['rim_diameter'] = df['rim_diameter'].apply(normalize_diameter)
    if 'filter_type' in df.columns:
        df['filter_type'] = df['filter_type'].apply(
            lambda x: str(x).split(';')[0].strip() if pd.notna(x) else None
        )
    return df


def clean_fdrive_tyres(df: pd.DataFrame) -> pd.DataFrame:
    """Fdrive шины: маппинг + нормализация."""
    df = df.copy()

    drop_cols = ['slug', 'listing_page', 'listing_index',
                 'price_without_discount', 'quantity_available_text',
                 'promotions', 'brand_slug', 'tyre_auto_type_id', 'tyre_stud_type_id', 'product_type', 
                 'freedom_tyre_promotion_percent', 'is_freedom_tyre_promotion', 'quantity_available']
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True)

    df.rename(columns={k: v for k, v in RENAME_FDRIVE_TYRES.items() if k in df.columns}, inplace=True)

    if 'category' in df.columns:
        df.rename(columns={'category': 'category_group'}, inplace=True)

    df = drop_empty_columns(df)
    df = drop_duplicates(df, 'fdrive_tyres')

    df['normalized_name'] = df['name'].apply(normalized_name)
    df['brand']           = df['brand'].apply(lambda x: clean_brand(x, BRAND_DICT))
    df['price']           = df['price'].apply(clean_price)
    df['season']          = df['season'].apply(normalize_season)
    df['rim_diameter']    = df['rim_diameter'].apply(normalize_diameter) if 'rim_diameter' in df.columns else None
    df['speed_index']     = df['speed_index'].apply(normalize_speed_index) if 'speed_index' in df.columns else None

    if 'stud_type' in df.columns:
        df['stud_type'] = df['stud_type'].apply(
            lambda x: True if x == 'studded' else (False if pd.notna(x) else None)
        )
    df['source'] = 'Freedom Drive'
    return df


def clean_fdrive_masla(df: pd.DataFrame) -> pd.DataFrame:
    """Fdrive масла: дроп колонок, маппинг, нормализация."""
    df = df.copy()

    drop_cols = ['slug', 'brand', 'listing_page', 'listing_index', 'brand_code', 'is_duplicate' ]
    df.drop(columns=[c for c in drop_cols if c in df.columns], inplace=True)

    df = df.loc[:, ~df.columns.duplicated()]

    df.rename(columns={
        'product_id':          'product_id',    
        'price_old':           'old_price',
        'brand_name':          'brand',
        'Объем упаковки, л':   'volume_raw',
        'Класс вязкости SAE':  'viscosity',
        'Класс API':           'specification',
        'Вид масла':           'oil_type',
        'Область применения':  'application',
        'Тип':                 'product_subtype',
        'Тип коробки передач': 'transmission_type',
        'Вязкость по SAE':     'viscosity_trans',
        'Стандарт API':        'api_standard',
        'Стандарт DOT':        'dot_standard',
        'Концентрат':          'is_concentrate',
        'Специализация':       'specialization',
        'Индекс допуска VAG':   'vag_approval_index',
        'Цвет':                'color',
        'Действие':            'action',
        'category':            'category_group'
    }, inplace=True)

    df = df.loc[:, ~df.columns.duplicated()]
    df = drop_empty_columns(df)
    df = drop_duplicates(df, 'fdrive_masla')

    df['normalized_name'] = df['name'].apply(normalized_name)
    df['brand']           = df['brand'].apply(lambda x: clean_brand(x, BRAND_DICT)) if 'brand' in df.columns else None
    df['price']           = df['price'].apply(clean_price)
    df['old_price']       = df['old_price'].apply(clean_price) if 'old_price' in df.columns else None
    df['viscosity']       = df['viscosity'].apply(normalize_viscosity) if 'viscosity' in df.columns else None
    df['volume_liters']   = df['volume_raw'].apply(normalize_volume) if 'volume_raw' in df.columns else None
    df['oil_type']        = df['oil_type'].apply(normalize_oil_type) if 'oil_type' in df.columns else None
    df['is_concentrate']  = df['is_concentrate'].apply(normalize_bool) if 'is_concentrate' in df.columns else None
    df['source']          = 'Freedom Drive'
    df = df.drop(columns=['volume_raw'], errors='ignore')
    return df


def clean_price_history(df: pd.DataFrame, source: str) -> pd.DataFrame:
    """Общая чистка для price_history таблиц."""
    df = df.copy()
    df = drop_empty_columns(df)
    df = drop_duplicates(df, f'{source}_price_history')

    df['price']          = df['price'].apply(clean_price)
    df['old_price']      = df['old_price'].apply(clean_price) if 'old_price' in df.columns else None
    df['discount_price'] = df['discount_price'].apply(clean_price) if 'discount_price' in df.columns else None
    df['availability']   = df['availability'].apply(normalize_availability)
    df['price_date']     = pd.to_datetime(df['price_date'], errors='coerce')
    return df


CLEANERS = {
    'carcity_products':                 clean_carcity,
    'pitstopshop_products':             clean_pitstopshop,
    'almatyres_products':               clean_almatyers,
    'satu_products':                    clean_satu,
    'forte_productsname_normalization': clean_forte,
    'fdrive_tyres_almaty_full':         clean_fdrive_tyres,
    'fdrive_masla_i_zhidkosti_full':    clean_fdrive_masla,
    'carcity_price_history':            lambda df: clean_price_history(df, 'carcity'),
    'pitstopshop_price_history':        lambda df: clean_price_history(df, 'pitstopshop'),
}


def run_pipeline(file_path: str, source_name: str) -> pd.DataFrame:
    if source_name not in CLEANERS:
        raise ValueError(f"Неизвестный источник: {source_name}. "
                         f"Доступны: {list(CLEANERS.keys())}")
    df_raw = pd.read_csv(file_path, low_memory=False)
    print(f"[{source_name}] Загружено строк: {len(df_raw)}")
    df_clean = CLEANERS[source_name](df_raw)
    print(f"[{source_name}] После чистки: {len(df_clean)} строк, {len(df_clean.columns)} столбцов")
    return df_clean



SOURCE_LABELS = {
    'almatyres_products':               'Almatyers',
    'carcity_products':                 'Carcity',
    'pitstopshop_products':             'PitStopShop',
    'satu_products':                    'Satu',
    'forte_productsname_normalization': 'Forte',
    'fdrive_tyres_almaty_full':         'Freedom Drive',
    'fdrive_masla_i_zhidkosti_full':    'Freedom Drive',
}
 
 
def merge_all_sources(cleaned_dfs: dict) -> pd.DataFrame:

    parts = []
 
    for source_name, df in cleaned_dfs.items():
        df = df.copy()
 
        if 'source' not in df.columns or df['source'].isna().all():
            df['source'] = SOURCE_LABELS.get(source_name, source_name)
        if 'source_site' in df.columns and df['source'].isna().all():
            df['source'] = df['source_site']
 
        df['source_file'] = source_name
 
        parts.append(df)
        print(f"  [merge] {source_name}: {len(df):,} строк")
 
    unified = pd.concat(parts, ignore_index=True, join='outer')
 
    numeric_cols = [
        'price', 'old_price', 'rim_diameter',
        'width(mm)', 'profile_height(%)', 'load_index', 'volume_liters',
    ]
    for col in numeric_cols:
        if col in unified.columns:
            unified[col] = pd.to_numeric(unified[col], errors='coerce')
 
    print(f"\n[merge] Итого: {len(unified):,} строк, {len(unified.columns)} колонок")
    print("[merge] Строк по источникам:")
    for src, cnt in unified['source'].value_counts().items():
        print(f"  {src}: {cnt:,}")
 
    return unified

from sqlalchemy import create_engine

def load_to_db(df: pd.DataFrame, table_name: str, db_url: str):
    engine = create_engine(db_url)
    df.to_sql(
        name=table_name,
        con=engine,
        if_exists='append',  
        index=False,
        method='multi',       
        chunksize=1000,
    )
    print(f"[db] Загружено {len(df):,} строк в таблицу '{table_name}'")
 

 
if __name__ == '__main__':
    FILES = {
        'cleaned_carcity_products':                 'parsed_data/carcity/carcity_products.csv',
        'cleaned_pitstopshop_products':             'parsed_data/pitstopshop/pitstopshop_products.csv',
        'cleaned_almatyres_products':               'parsed_data/almatyers/almatyres_products.csv',
        'cleaned_satu_products':                    'parsed_data/satu/satu_products.csv',
        'cleaned_forte_productsname_normalization': 'parsed_data/forte/forte_productsname_normalization.csv',
        'cleaned_fdrive_tyres_almaty_full':         'parsed_data/fdrive/fdrive_tyres_almaty_full.csv',
        'cleaned_fdrive_masla_i_zhidkosti_full':    'parsed_data/fdrive/fdrive_masla_i_zhidkosti_full.csv',
        'cleaned_carcity_price_history':            'parsed_data/carcity/carcity_price_history.csv',
        'cleaned_pitstopshop_price_history':        'parsed_data/pitstopshop/pitstopshop_price_history.csv',
    }
 
    OUTPUT_DIR = '/Users/meryetsalijanova/Documents/freedom drive/cleaned'
 
    cleaned_dfs = {}
    for source_name, path in FILES.items():
        df_clean = run_pipeline(path, source_name)
        out_path = f'{OUTPUT_DIR}/{source_name}_clean.csv'
        df_clean.to_csv(out_path, index=False)
        print(f"  Сохранено: {out_path}\n")
        if 'price_history' not in source_name:
            cleaned_dfs[source_name] = df_clean
 
    print("\nОбъединение датасетов (outer)")
    unified_df = merge_all_sources(cleaned_dfs)
    unified_path = f'{OUTPUT_DIR}/unified_products.csv'
    unified_df.to_csv(unified_path, index=False)
    print(f"\n[merge] Сохранено: {unified_path}")

    DB_URL = 'postgresql://readonly_user:ZpUSlM6Hdsc1tp14@91.243.71.68:5870/fdrive'
    load_to_db(unified_df, table_name='unified_products', db_url=DB_URL)
 