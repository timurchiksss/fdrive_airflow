"""cross-merchant product matching pipeline.

loads the per-merchant `cleanned.*` tables, matches equivalent products across
merchants per category (tires, oils, filters, batteries)

picks the merchant with the most unique matched items as the root merchant

assigns each match a leaf `category_id`, and writes `skus` / `sku_source_mapping` tables.
"""

import logging
import os
import re

import pandas as pd
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

TABLE_CONFIG = {
    "tires": {
        "tables": ["fdrive_tires", "forte_market_tires", "satu_tires", "carcity_tires"],
        "extra_cols": ["tire_width", "tire_profile", "tire_diameter", "season"],
    },
    "oils": {
        "tables": ["fdrive_oils", "forte_market_oils", "satu_oils", "carcity_oils"],
        "extra_cols": ["viscosity", "volume_liters", "oil_type"],
    },
    "filters": {
        "tables": ["forte_market_filters", "satu_filters", "carcity_filters"],
        "extra_cols": ["filter_type", "oem_number"],
    },
    "batteries": {
        "tables": ["forte_market_batteries", "satu_batteries", "carcity_batteries"],
        "extra_cols": ["capacity_ah", "voltage_v"],
    },
}

BASE_COLS = ["source", "source_product_id", "product_name", "normalized_name", "brand", "price", "loaded_at"]


def get_engine() -> Engine:
    host = os.environ.get("DB_HOST") or os.environ.get("PGHOST", "localhost")
    port = os.environ.get("DB_PORT") or os.environ.get("PGPORT", "5432")
    name = os.environ.get("DB_NAME") or os.environ.get("PGDATABASE", "fdrive")
    user = os.environ.get("DB_USER") or os.environ.get("PGUSER", "postgres")
    password = os.environ.get("DB_PASSWORD") or os.environ.get("PGPASSWORD", "")
    return create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}")


def clean_schema() -> str:
    return os.environ.get("CLEAN_SCHEMA", "cleanned")


def output_schema() -> str:
    return os.environ.get("MATCH_SCHEMA", "matching")


def q_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# generic хелперы
# ---------------------------------------------------------------------------

def clean_text(text_val):
    if pd.isna(text_val):
        return ""
    text_val = text_val.lower()
    text_val = re.sub(r'[^\w\s]', ' ', text_val)
    text_val = re.sub(r'\s+', ' ', text_val).strip()
    return text_val


def number_penalty(name1, name2):
    """Penalize matches whose numeric tokens (viscosity, tyre size, etc.) disagree."""
    nums1 = set(re.findall(r'\b\d+\b', str(name1).lower()))
    nums2 = set(re.findall(r'\b\d+\b', str(name2).lower()))
    if not nums1 or not nums2:
        return 1.0
    overlap = nums1 & nums2
    if not overlap:
        return 0.2
    if len(overlap) / max(len(nums1), len(nums2)) < 0.5:
        return 0.6
    return 1.0


# ---- oils-specific ----
OIL_STOP_WORDS = ["моторное", "масло", "oil", "масла", "motor", "для", "двигателя",
                  "синтетическое", "полусинтетическое", "минеральное"]


def clean_text_oils(text_val):
    if pd.isna(text_val):
        return ""
    text_val = str(text_val).lower()
    text_val = re.sub(r'[^\w\s]', ' ', text_val)
    words = [w for w in text_val.split() if w not in OIL_STOP_WORDS]
    return " ".join(words).strip()


def extract_viscosity_from_name(name):
    match = re.search(r'\b\d+w-\d+\b', str(name).lower())
    return match.group(0) if match else "unknown"


def clean_volume(val):
    if pd.isna(val):
        return "unknown"
    val = str(val).lower().strip()
    val = val.replace("л", "").replace("l", "").replace("литр", "")
    val = val.replace(",", ".").strip()
    try:
        return str(round(float(val)))
    except ValueError:
        return "unknown"


def extract_volume_from_name(name):
    if pd.isna(name):
        return "unknown"
    name = str(name).lower()
    patterns = [
        r'\((\d+(?:[.,]\d+)?)\s*[lл]\)',
        r'\b(\d+(?:[.,]\d+)?)\s*[lл]\b',
        r'\b(\d+(?:[.,]\d+)?)\s*литр',
    ]
    for pattern in patterns:
        match = re.search(pattern, name)
        if match:
            try:
                return str(round(float(match.group(1).replace(",", "."))))
            except ValueError:
                continue
    return "unknown"


def clean_oil_type(val):
    if pd.isna(val):
        return "unknown"
    val = str(val).lower().strip()
    if any(w in val for w in ["синтет", "synthetic", "full syn"]):
        return "synthetic"
    if any(w in val for w in ["полусинт", "semi", "п/синт"]):
        return "semi"
    if any(w in val for w in ["минерал", "mineral"]):
        return "mineral"
    return "unknown"


OIL_PRODUCT_LINES = [
    "EDGE", "VECTON", "MAGNATEC", "XTC", "XTRA",
    "DELVAC", "GRAND TOURING", "HYPER ECODRIVE", "ULTIMA",
    "GENESIS", "MOLYGEN", "LEICHTLAUF", "TITAN",
    "LONGLIFE", "A-LINE", "SYNT-S", "RUBIA", "GTD",
    "SUPER 2000", "SUPER 3000", "DIESEL LEICHTLAUF",
    "REVOLUX", "GIDROTEC", "PREMIUM",
]


def extract_oil_product_line(name):
    if pd.isna(name):
        return "unknown"
    name_upper = str(name).upper()
    for line in OIL_PRODUCT_LINES:
        if line in name_upper:
            return line.lower().replace(" ", "_")
    return "unknown"


KNOWN_BRANDS = [
    "bardahl", "castrol", "mobil", "shell", "liqui moly",
    "motul", "total", "lube", "yacco", "valvoline", "elf",
    "gulf", "eneos", "mannol", "lukoil", "gazpromneft",
]


def extract_brand_from_name(name):
    if pd.isna(name):
        return "unknown"
    name_lower = str(name).lower()
    for brand in KNOWN_BRANDS:
        if brand in name_lower:
            return brand
    return "unknown"


# ---- tyre-specific----
def clean_width(val):
    if pd.isna(val) or str(val).strip() == "":
        return "unknown"
    val = str(val).lower().strip().replace("мм", "").replace('"', "").replace("'", "")
    val = val.split("/")[0].split(";")[0].strip()
    try:
        return str(round(float(val)))
    except ValueError:
        return "unknown"


def clean_diameter(val):
    if pd.isna(val) or str(val).strip() == "":
        return "unknown"
    val = str(val).lower().strip().replace("r", "").replace('"', "").replace("'", "").replace("с", "")
    val = val.split(";")[0].strip()
    try:
        return str(round(float(val)))
    except ValueError:
        return "unknown"


def clean_season(val):
    if pd.isna(val):
        return "unknown"
    val = str(val).lower().strip()
    if any(w in val for w in ["winter", "зимн", "шип", "ice", "stud"]):
        return "winter"
    if any(w in val for w in ["summer", "летн", "sport"]):
        return "summer"
    if any(w in val for w in ["all", "всесез", "season", "4s"]):
        return "allseason"
    return "unknown"


def extract_tyre_model(name):
    if pd.isna(name) or str(name).strip() == "":
        return "unknown"
    name = re.sub(r'\d+/\d+\s*r?\d+', '', str(name))
    name = re.sub(r'\b\d{3}\b', '', name)
    words = name.split()
    return "_".join(words[1:3]).strip() if len(words) > 1 else "unknown"


def extract_speed_index(name):
    if pd.isna(name) or str(name).strip() == "":
        return "unknown"
    matches = re.findall(r'\b\d{2,3}([A-Z])\b', str(name).upper())
    return matches[-1].lower() if matches else "unknown"


def tyre_size_penalty(name1, name2):
    """Hard penalty when the raw 'WWW/PP R DD' size string in the two names disagrees."""
    pattern = r'(\d{3})\s*/\s*(\d{2})\s*r\s*(\d{2})'
    m1 = re.search(pattern, str(name1).lower())
    m2 = re.search(pattern, str(name2).lower())
    if m1 and m2 and m1.groups() != m2.groups():
        return 0.1
    return 1.0


# ---- filters/batteries  ----
def clean_filter_type(val):
    if pd.isna(val):
        return "unknown"
    val = str(val).lower().strip()
    if any(w in val for w in ["воздушный", "air"]):
        return "air"
    if any(w in val for w in ["масляный", "oil"]):
        return "oil"
    if any(w in val for w in ["салонный", "cabin"]):
        return "cabin"
    if any(w in val for w in ["топливный", "fuel"]):
        return "fuel"
    if "трансмиссионный" in val:
        return "transmission"
    if "гидравлический" in val:
        return "hydraulic"
    return "unknown"


def extract_article(name):
    if not isinstance(name, str):
        return "unknown"
    matches = re.findall(r'[A-Z]{2,}[\d]+[A-Z\d]*', name)
    if matches:
        return matches[-1].lower()
    return "unknown"


def clean_capacity(val):
    if pd.isna(val):
        return "unknown"
    try:
        return str(round(float(val)))
    except (TypeError, ValueError):
        return "unknown"


def extract_battery_model(name):
    if not name:
        return "unknown"
    matches = re.findall(r's\d+|silver|blue|black|asia|agm', name)
    if matches:
        return matches[0]
    return "unknown"


def extract_vehicle_type(name):
    if not name:
        return "passenger"
    if any(w in name for w in ["suv", "кроссовер", "внедорожник"]):
        return "suv"
    if any(w in name for w in ["грузов", "truck"]):
        return "truck"
    if any(w in name for w in ["мотошин", "мотоцикл", "moto"]):
        return "moto"
    return "passenger"


def extract_studded(name):
    if not name:
        return None
    if "нешип" in name:
        return False
    if "шип" in name:
        return True
    return None


def extract_battery_type(name):
    if not isinstance(name, str):
        return None
    name = name.upper()
    for bt in ["AGM", "EFB", "GEL"]:
        if bt in name:
            return bt
    return None


def get_category_id(category_group, oil_type=None, season=None, vehicle_type=None,
                     studded=None, filter_type=None, battery_type=None):
    g = str(category_group).lower().strip() if category_group else ''

    if g == 'oils':
        oil = str(oil_type).lower().strip() if oil_type else ''
        return {'synthetic': 4, 'semi-synthetic': 5, 'mineral': 6, 'flush': 7}.get(oil, 3)

    if g in ('tires', 'tyres'):
        vt = str(vehicle_type).lower().strip() if vehicle_type else 'passenger'
        s = str(season).lower().strip() if season else ''

        if vt == 'suv':
            return {'summer': 38, 'winter': 39, 'all_season': 40}.get(s, 38)
        if vt == 'truck':
            return 42
        if vt == 'moto':
            return 44

        if s == 'winter':
            if studded is True:
                return 34
            if studded is False:
                return 35
            return 33
        return {'summer': 32, 'all_season': 36}.get(s, 32)

    if g == 'filters':
        ft = str(filter_type).strip() if filter_type else ''
        return {
            'Воздушный': 61, 'Масляный': 62, 'Салонный': 63,
            'Топливный': 64, 'Трансмиссионный': 65, 'Гидравлический': 66,
        }.get(ft, 60)

    if g == 'batteries':
        bt = str(battery_type).strip() if battery_type else ''
        return {'AGM': 53, 'EFB': 54, 'GEL': 55}.get(bt, 52)

    return 999


OIL_TYPE_MAP = {"synthetic": "synthetic", "semi": "semi-synthetic", "mineral": "mineral"}
SEASON_MAP = {"winter": "winter", "summer": "summer", "allseason": "all_season"}
FILTER_TYPE_MAP = {
    "air": "Воздушный", "oil": "Масляный", "cabin": "Салонный",
    "fuel": "Топливный", "transmission": "Трансмиссионный", "hydraulic": "Гидравлический",
}


def assign_category_id(row):
    cat = row["category"]
    if cat == "oils":
        return get_category_id("oils", oil_type=OIL_TYPE_MAP.get(row["oil_type_clean"]))
    if cat == "tires":
        return get_category_id(
            "tires",
            season=SEASON_MAP.get(row["season_clean"]),
            vehicle_type=row["vehicle_type"],
            studded=row["studded"],
        )
    if cat == "filters":
        return get_category_id("filters", filter_type=FILTER_TYPE_MAP.get(row["filter_type_clean"]))
    if cat == "batteries":
        return get_category_id("batteries", battery_type=row["battery_type"])
    return 999


def confidence_bucket(score, method):
    if method in ("OEM", "root", "single_source") or score >= 0.9:
        return "High"
    if score >= 0.75:
        return "Medium"
    return "Low"


def find_matches_in_groups(model, data, group_col, threshold, match_type,
                            require_multi_source=True, exclude_unknown=True,
                            exclude_substring="unknown", max_group_size=None,
                            penalty_fn=None, check_brand=False, name_col="name_clean"):
    """Embed names within each group and pair up cross-merchant matches above threshold."""
    matches = []
    for group_key, group in data.groupby(group_col):
        if len(group) < 2:
            continue
        if require_multi_source and group["source"].nunique() < 2:
            continue
        if exclude_unknown and exclude_substring in str(group_key):
            continue
        if max_group_size and len(group) > max_group_size:
            continue

        names = group[name_col].tolist()
        embeddings = model.encode(names, batch_size=64, show_progress_bar=False)
        sim_matrix = cosine_similarity(embeddings)

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if group.iloc[i]["source"] == group.iloc[j]["source"]:
                    continue

                if check_brand:
                    brand_i = extract_brand_from_name(group.iloc[i]["normalized_name"])
                    brand_j = extract_brand_from_name(group.iloc[j]["normalized_name"])
                    if brand_i != "unknown" and brand_j != "unknown" and brand_i != brand_j:
                        continue

                score = float(sim_matrix[i][j])
                if penalty_fn:
                    score *= penalty_fn(group.iloc[i]["normalized_name"], group.iloc[j]["normalized_name"])

                if score >= threshold:
                    matches.append({
                        "sku_1": group.iloc[i]["sku_id"],
                        "sku_2": group.iloc[j]["sku_id"],
                        "source_1": group.iloc[i]["source"],
                        "source_2": group.iloc[j]["source"],
                        "category": group.iloc[i]["category"],
                        "score": round(score, 3),
                        "match_type": match_type,
                    })
    return pd.DataFrame(matches)


# ---------------------------------------------------------------------------
# pipeline stages
# ---------------------------------------------------------------------------

def load_data(engine: Engine) -> pd.DataFrame:
    frames = []
    schema = clean_schema()
    for category, cfg in TABLE_CONFIG.items():
        for table in cfg["tables"]:
            cols = BASE_COLS + cfg["extra_cols"]
            columns_sql = ", ".join(q_ident(col) for col in cols)
            d = pd.read_sql(f"SELECT {columns_sql} FROM {q_ident(schema)}.{q_ident(table)}", engine)
            d["category"] = category
            d["sku_id"] = table + ":" + d["source_product_id"].astype(str)
            frames.append(d)

    df = pd.concat(frames, ignore_index=True)

    # cleanned.* tables accumulate one row per Airflow DAG run instead of upserting, so
    # the same sku_id can show up several times (identical content, different loaded_at) -
    # keep only the most recent load of each sku_id before any matching happens
    dup_rows = df.duplicated(subset="sku_id").sum()
    df = df.sort_values("loaded_at").drop_duplicates(subset="sku_id", keep="last").reset_index(drop=True)
    if dup_rows:
        logger.info("Dropped %s duplicate-load rows (re-ingested sku_id)", dup_rows)

    df["name_clean"] = df["normalized_name"].apply(clean_text)
    df["brand_clean"] = df["brand"].fillna("unknown").str.lower().str.strip()

    logger.info("Loaded %s rows total", len(df))
    return df


def match_tires(df: pd.DataFrame, model: SentenceTransformer) -> tuple[pd.DataFrame, pd.DataFrame]:
    tires_df = df[df["category"] == "tires"].copy()

    tires_df["width_clean"] = tires_df["tire_width"].apply(clean_width)
    tires_df["profile_clean"] = tires_df["tire_profile"].fillna("unknown").astype(str).str.replace('"', "").str.strip()
    tires_df["diameter_clean"] = tires_df["tire_diameter"].apply(clean_diameter)
    tires_df["season_clean"] = tires_df["season"].apply(clean_season)
    tires_df["model_clean"] = tires_df["name_clean"].apply(extract_tyre_model)
    tires_df["speed_index_clean"] = tires_df["name_clean"].apply(extract_speed_index)

    tires_df["group_key"] = (
        tires_df["brand_clean"] + "_" + tires_df["model_clean"] + "_" +
        tires_df["width_clean"] + "_" + tires_df["profile_clean"] + "_" +
        tires_df["diameter_clean"] + "_" + tires_df["season_clean"] + "_" +
        tires_df["speed_index_clean"]
    )

    # exclude_substring uses the narrower rule (3 unknown fields in a row) since the extra
    # width/profile/diameter/speed_index dimensions are frequently unknown on their own
    tires_results = find_matches_in_groups(
        model, tires_df, "group_key", threshold=0.75, match_type="NLP",
        exclude_substring="unknown_unknown_unknown",
        penalty_fn=lambda n1, n2: number_penalty(n1, n2) * tyre_size_penalty(n1, n2),
    )
    logger.info("Tire groups: %s | matches: %s", tires_df["group_key"].nunique(), len(tires_results))
    return tires_df, tires_results


def match_oils(df: pd.DataFrame, model: SentenceTransformer) -> tuple[pd.DataFrame, pd.DataFrame]:
    oils_df = df[df["category"] == "oils"].copy()

    # stop-word-stripped variant of name_clean, used only for oil embeddings
    oils_df["name_clean"] = oils_df["normalized_name"].apply(clean_text_oils)

    oils_df["viscosity_clean"] = oils_df["viscosity"].fillna("unknown").str.lower().str.strip()
    unknown_visc = oils_df["viscosity_clean"] == "unknown"
    oils_df.loc[unknown_visc, "viscosity_clean"] = oils_df.loc[unknown_visc, "normalized_name"].apply(extract_viscosity_from_name)

    oils_df["volume_clean"] = oils_df["volume_liters"].apply(clean_volume)
    unknown_vol = oils_df["volume_clean"] == "unknown"
    oils_df.loc[unknown_vol, "volume_clean"] = oils_df.loc[unknown_vol, "normalized_name"].apply(extract_volume_from_name)

    oils_df["oil_type_clean"] = oils_df["oil_type"].apply(clean_oil_type)
    unknown_type = oils_df["oil_type_clean"] == "unknown"
    oils_df.loc[unknown_type, "oil_type_clean"] = oils_df.loc[unknown_type, "name_clean"].apply(clean_oil_type)

    oils_df["product_line_clean"] = oils_df["normalized_name"].apply(extract_oil_product_line)

    oils_df["group_key"] = (
        oils_df["brand_clean"] + "_" + oils_df["product_line_clean"] + "_" +
        oils_df["viscosity_clean"] + "_" + oils_df["volume_clean"] + "_" + oils_df["oil_type_clean"]
    )

    oils_results = find_matches_in_groups(
        model, oils_df, "group_key", threshold=0.75, match_type="NLP", exclude_unknown=False,
        penalty_fn=number_penalty, check_brand=True,
    )
    logger.info("Oil groups: %s | matches: %s", oils_df["group_key"].nunique(), len(oils_results))
    return oils_df, oils_results


def match_filters(df: pd.DataFrame, model: SentenceTransformer) -> tuple[pd.DataFrame, pd.DataFrame]:
    filters_df = df[df["category"] == "filters"].copy()

    filters_df["filter_type_clean"] = filters_df["filter_type"].apply(clean_filter_type)
    filters_df["oem_clean"] = (
        filters_df["oem_number"].fillna("unknown").str.lower().str.strip()
        .str.replace(" ", "").str.replace("-", "")
    )
    filters_df["article"] = filters_df["product_name"].apply(extract_article)
    filters_df["group_key"] = (
        filters_df["brand_clean"] + "_" + filters_df["filter_type_clean"] + "_" + filters_df["article"]
    )

    # 1. exact OEM matches
    oem_matches = []
    oem_df = filters_df[filters_df["oem_clean"] != "unknown"]
    for oem, group in oem_df.groupby("oem_clean"):
        if len(group) < 2 or group["source"].nunique() < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if group.iloc[i]["source"] == group.iloc[j]["source"]:
                    continue
                oem_matches.append({
                    "sku_1": group.iloc[i]["sku_id"], "sku_2": group.iloc[j]["sku_id"],
                    "source_1": group.iloc[i]["source"], "source_2": group.iloc[j]["source"],
                    "category": "filters", "score": 1.0, "match_type": "OEM",
                })
    oem_results = pd.DataFrame(oem_matches).drop_duplicates(subset=["sku_1", "sku_2"])

    # 2. NLP fallback on brand + filter_type + article (skip huge groups)
    nlp_results = find_matches_in_groups(model, filters_df, "group_key", threshold=0.75,
                                          match_type="NLP", max_group_size=30)

    filters_results = pd.concat([oem_results, nlp_results], ignore_index=True)
    if not filters_results.empty:
        filters_results = filters_results.drop_duplicates(subset=["sku_1", "sku_2"])
    logger.info("Filter OEM matches: %s | NLP matches: %s | total: %s",
                len(oem_results), len(nlp_results), len(filters_results))
    return filters_df, filters_results


def match_batteries(df: pd.DataFrame, model: SentenceTransformer) -> tuple[pd.DataFrame, pd.DataFrame]:
    batteries_df = df[df["category"] == "batteries"].copy()

    batteries_df["capacity_clean"] = batteries_df["capacity_ah"].apply(clean_capacity)
    batteries_df["model_clean"] = batteries_df["name_clean"].apply(extract_battery_model)
    batteries_df["group_key"] = (
        batteries_df["brand_clean"] + "_" + batteries_df["model_clean"] + "_" + batteries_df["capacity_clean"]
    )

    batteries_results = find_matches_in_groups(model, batteries_df, "group_key", threshold=0.75, match_type="NLP")
    logger.info("Battery groups: %s | matches: %s", batteries_df["group_key"].nunique(), len(batteries_results))
    return batteries_df, batteries_results


def pick_root_merchant(final_results: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    sku_source = pd.concat([
        final_results[["sku_1", "source_1"]].rename(columns={"sku_1": "sku_id", "source_1": "source"}),
        final_results[["sku_2", "source_2"]].rename(columns={"sku_2": "sku_id", "source_2": "source"}),
    ]).drop_duplicates()

    merchant_unique_counts = sku_source.groupby("source")["sku_id"].nunique().sort_values(ascending=False)
    root_merchant = merchant_unique_counts.idxmax()
    logger.info("Root merchant: %s (%s unique matched items)", root_merchant, merchant_unique_counts.max())
    return root_merchant, sku_source


def build_groups(final_results: pd.DataFrame, sku_source: pd.DataFrame, root_merchant: str):
    parent = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for _, row in final_results.iterrows():
        union(row["sku_1"], row["sku_2"])

    sku_to_source = dict(zip(sku_source["sku_id"], sku_source["source"]))

    components = {}
    for sku in parent:
        components.setdefault(find(sku), []).append(sku)

    # anchor each component on a root_merchant item if one exists in the group
    group_root = {}
    for comp_root, skus in components.items():
        root_candidates = [s for s in skus if sku_to_source[s] == root_merchant]
        anchor = root_candidates[0] if root_candidates else comp_root
        for s in skus:
            group_root[s] = anchor

    logger.info("Total matched items: %s | total groups: %s", len(group_root), len(components))
    return components, group_root


def assign_categories(df, tires_df, oils_df, filters_df, batteries_df) -> pd.DataFrame:
    tires_df["vehicle_type"] = tires_df["name_clean"].apply(extract_vehicle_type)
    tires_df["studded"] = tires_df["name_clean"].apply(extract_studded)
    batteries_df["battery_type"] = batteries_df["product_name"].apply(extract_battery_type)

    tires_df["category_id"] = tires_df.apply(assign_category_id, axis=1)
    oils_df["category_id"] = oils_df.apply(assign_category_id, axis=1)
    filters_df["category_id"] = filters_df.apply(assign_category_id, axis=1)
    batteries_df["category_id"] = batteries_df.apply(assign_category_id, axis=1)

    category_map = pd.concat([
        tires_df[["sku_id", "category_id"]],
        oils_df[["sku_id", "category_id"]],
        filters_df[["sku_id", "category_id"]],
        batteries_df[["sku_id", "category_id"]],
    ], ignore_index=True).drop_duplicates(subset="sku_id")

    df = df.drop(columns=["category_id"], errors="ignore")
    df = df.merge(category_map, on="sku_id", how="left")
    assert df["category_id"].notna().all(), "every product should get a category_id"
    df["category_id"] = df["category_id"].astype(int)
    return df


def fetch_source_urls(engine: Engine, df: pd.DataFrame) -> pd.DataFrame:
    url_frames = []
    schema = clean_schema()
    for category, cfg in TABLE_CONFIG.items():
        for table in cfg["tables"]:
            d = pd.read_sql(
                f"SELECT source_product_id, source_url FROM {q_ident(schema)}.{q_ident(table)}",
                engine,
            )
            d["sku_id"] = table + ":" + d["source_product_id"].astype(str)
            url_frames.append(d[["sku_id", "source_url"]])

    url_map = pd.concat(url_frames, ignore_index=True).drop_duplicates(subset="sku_id")

    df = df.drop(columns=["source_url"], errors="ignore")
    df = df.merge(url_map, on="sku_id", how="left")
    logger.info("source_url coverage: %.3f", df["source_url"].notna().mean())
    return df


def build_master_skus(df: pd.DataFrame, components: dict, group_root: dict):
    df = df.drop_duplicates(subset="sku_id").reset_index(drop=True)
    products_lookup = df.set_index("sku_id")

    all_components = {k: list(v) for k, v in components.items()}
    all_group_root = dict(group_root)

    for sku in df["sku_id"]:
        if sku not in all_group_root:
            all_components[sku] = [sku]
            all_group_root[sku] = sku

    def pick_category_id(members):
        cats = products_lookup.loc[members, "category_id"]
        return int(cats.mode().iloc[0])

    skus_records = []
    sku_id_map = {}

    for i, members in enumerate(all_components.values(), start=1):
        anchor = all_group_root[members[0]]
        master_id = f"sku_{i:011d}"
        sku_id_map[anchor] = master_id

        anchor_row = products_lookup.loc[anchor]
        source_id = [
            {"id": products_lookup.loc[m, "source_product_id"], "source": products_lookup.loc[m, "source"]}
            for m in members
        ]

        skus_records.append({
            "id": master_id,
            "name": anchor_row["normalized_name"],
            "brand": anchor_row["brand"],
            "category_id": pick_category_id(members),
            "normalized_description": anchor_row["name_clean"],
            "status": "active",
            "source_id": source_id,
            "is_szpt": False,
        })

    skus_df = pd.DataFrame(skus_records)
    multi_source = sum(len(m) > 1 for m in all_components.values())
    logger.info("Generated %s master SKUs (%s multi-source)", len(skus_df), multi_source)
    return skus_df, sku_id_map, all_components, all_group_root, products_lookup


def build_sku_source_mapping(final_results, all_components, all_group_root, sku_id_map, products_lookup):
    pair_info = {}
    for _, r in final_results.iterrows():
        key = frozenset({r["sku_1"], r["sku_2"]})
        score, method = r["score"], r["match_type"]
        prev = pair_info.get(key)
        if prev is None or score > prev[0]:
            pair_info[key] = (score, method)

    mapping_records = []
    for members in all_components.values():
        anchor = all_group_root[members[0]]
        master_id = sku_id_map[anchor]

        for m in members:
            row = products_lookup.loc[m]
            if m == anchor:
                score, method = 1.0, "root" if len(members) > 1 else "single_source"
            else:
                best = None
                for other in members:
                    if other == m:
                        continue
                    info = pair_info.get(frozenset({m, other}))
                    if info and (best is None or info[0] > best[0]):
                        best = info
                score, method = best if best else (0.0, "NLP")

            mapping_records.append({
                "sku_id": master_id,
                "source": row["source"],
                "source_product_id": row["source_product_id"],
                "source_product_name": row["product_name"],
                "source_url": row["source_url"],
                "match_method": method,
                "match_score": round(float(score), 3),
                "match_confidence": confidence_bucket(score, method),
            })

    sku_source_mapping = pd.DataFrame(mapping_records)
    logger.info("sku_source_mapping rows: %s", len(sku_source_mapping))
    return sku_source_mapping


def write_master_tables(engine: Engine, skus_df: pd.DataFrame, sku_source_mapping: pd.DataFrame) -> None:
    schema = output_schema()
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {q_ident(schema)}"))

    # source_id is already a list[dict]; let SQLAlchemy's JSONB type serialize it -
    # pre-encoding with json.dumps here would double-encode it into a JSON string column
    skus_df.to_sql("skus", engine, schema=schema, if_exists="replace", index=False,
                    dtype={"source_id": JSONB}, method="multi", chunksize=5000)
    sku_source_mapping.to_sql("sku_source_mapping", engine, schema=schema, if_exists="replace",
                               index=False, method="multi", chunksize=5000)
    logger.info("Saved %s.skus and %s.sku_source_mapping", schema, schema)


def run_pipeline(engine: Engine) -> None:
    model = SentenceTransformer(MODEL_NAME)

    df = load_data(engine)

    tires_df, tires_results = match_tires(df, model)
    oils_df, oils_results = match_oils(df, model)
    filters_df, filters_results = match_filters(df, model)
    batteries_df, batteries_results = match_batteries(df, model)

    final_results = pd.concat(
        [tires_results, oils_results, filters_results, batteries_results],
        ignore_index=True,
    ).drop_duplicates(subset=["sku_1", "sku_2"])
    logger.info("Total matches: %s", len(final_results))

    root_merchant, sku_source = pick_root_merchant(final_results)
    components, group_root = build_groups(final_results, sku_source, root_merchant)

    df = assign_categories(df, tires_df, oils_df, filters_df, batteries_df)
    df = fetch_source_urls(engine, df)

    skus_df, sku_id_map, all_components, all_group_root, products_lookup = build_master_skus(
        df, components, group_root
    )
    sku_source_mapping = build_sku_source_mapping(
        final_results, all_components, all_group_root, sku_id_map, products_lookup
    )

    write_master_tables(engine, skus_df, sku_source_mapping)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = get_engine()
    run_pipeline(engine)


if __name__ == "__main__":
    main()
