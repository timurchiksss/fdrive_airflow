"""cross-merchant product matching pipeline.

loads the per-merchant `cleanned.*` tables, matches equivalent products across
merchants per category (tires, oils, filters, batteries)

picks the merchant with the most unique matched items as the root merchant

assigns each match a leaf `category_id`, and writes `skus` / `sku_source_mapping` tables.
"""

import logging
import os
import re
import uuid
from itertools import combinations

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

UNKNOWN_VALUES = {"", "unknown", "none", "nan", "null", "не указано", "нет данных", "-"}

CANDIDATE_RULES = {
    "tires": {
        "block_attrs": ["width_clean", "profile_clean", "diameter_clean"],
        "score_attrs": ["brand_clean", "width_clean", "profile_clean", "diameter_clean", "season_clean", "speed_index_clean"],
        "threshold": 0.78,
        "embedding_weight": 0.45,
        "rule_weight": 0.55,
        "match_type": "rules+embeddings",
    },
    "oils": {
        "block_attrs": ["viscosity_clean", "volume_clean"],
        "score_attrs": ["brand_clean", "viscosity_clean", "volume_clean", "oil_type_clean", "product_line_clean"],
        "threshold": 0.78,
        "embedding_weight": 0.45,
        "rule_weight": 0.55,
        "match_type": "rules+embeddings",
    },
    "filters": {
        "block_attrs": ["filter_type_clean"],
        "score_attrs": ["brand_clean", "filter_type_clean", "oem_clean", "article"],
        "threshold": 0.76,
        "embedding_weight": 0.40,
        "rule_weight": 0.60,
        "match_type": "rules+embeddings",
    },
    "batteries": {
        "block_attrs": ["capacity_clean", "voltage_clean"],
        "score_attrs": ["brand_clean", "capacity_clean", "voltage_clean", "battery_type_clean", "model_clean"],
        "threshold": 0.78,
        "embedding_weight": 0.45,
        "rule_weight": 0.55,
        "match_type": "rules+embeddings",
    },
}


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


def is_known(value) -> bool:
    if pd.isna(value):
        return False
    return str(value).strip().lower() not in UNKNOWN_VALUES


def hard_value(value) -> str:
    if not is_known(value):
        return "unknown"
    text = str(value).strip().lower()
    text = re.sub(r"\.0$", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def row_block_key(row: pd.Series, category: str, attrs: list[str]) -> tuple[str, ...] | None:
    values = [category, hard_value(row.get("brand_clean"))]
    if values[-1] == "unknown":
        return None
    for attr in attrs:
        value = hard_value(row.get(attr))
        if value == "unknown":
            return None
        values.append(value)
    return tuple(values)


def generate_candidates(data: pd.DataFrame, category: str, block_attrs: list[str],
                        max_block_size: int = 250) -> pd.DataFrame:
    """Stage 1: deterministic blocking by category + brand + hard attrs."""
    records = []
    if data.empty:
        return pd.DataFrame(records)

    work = data.copy()
    work["candidate_block_key"] = work.apply(lambda row: row_block_key(row, category, block_attrs), axis=1)
    work = work[work["candidate_block_key"].notna()]

    for block_key, group in work.groupby("candidate_block_key"):
        if len(group) < 2 or group["source"].nunique() < 2:
            continue
        if len(group) > max_block_size:
            logger.info("Skip oversized candidate block %s with %s rows", block_key, len(group))
            continue
        for left_idx, right_idx in combinations(group.index, 2):
            left = group.loc[left_idx]
            right = group.loc[right_idx]
            if left["source"] == right["source"]:
                continue
            records.append({
                "left_idx": left_idx,
                "right_idx": right_idx,
                "sku_1": left["sku_id"],
                "sku_2": right["sku_id"],
                "source_1": left["source"],
                "source_2": right["source"],
                "category": category,
                "candidate_block_key": "|".join(map(str, block_key)),
                "candidate_rule": f"category+brand+{'+'.join(block_attrs)}",
            })
    return pd.DataFrame(records).drop_duplicates(subset=["sku_1", "sku_2"])


def compare_hard_attrs(left: pd.Series, right: pd.Series, attrs: list[str]) -> tuple[float, dict]:
    matched = {}
    mismatched = {}
    missing = []
    weighted_score = 0.0
    total_weight = 0.0

    for attr in attrs:
        left_value = hard_value(left.get(attr))
        right_value = hard_value(right.get(attr))
        if left_value == "unknown" or right_value == "unknown":
            missing.append(attr)
            continue
        weight = 1.5 if attr in {"brand_clean", "width_clean", "profile_clean", "diameter_clean",
                                  "viscosity_clean", "volume_clean", "capacity_clean", "voltage_clean",
                                  "oem_clean"} else 1.0
        total_weight += weight
        if left_value == right_value:
            matched[attr] = {"left": left_value, "right": right_value}
            weighted_score += weight
        else:
            mismatched[attr] = {"left": left_value, "right": right_value}

    rule_score = weighted_score / total_weight if total_weight else 0.0
    explanation = {
        "matched_fields": matched,
        "mismatched_fields": mismatched,
        "missing_fields": missing,
    }
    return rule_score, explanation


def embedding_scores(model: SentenceTransformer, data: pd.DataFrame, candidate_pairs: pd.DataFrame,
                     name_col: str = "name_clean") -> dict[str, object]:
    sku_ids = pd.unique(pd.concat([candidate_pairs["sku_1"], candidate_pairs["sku_2"]], ignore_index=True))
    names = data.drop_duplicates("sku_id").set_index("sku_id").loc[sku_ids, name_col].fillna("").astype(str)
    vectors = model.encode(names.tolist(), batch_size=64, show_progress_bar=False)
    return dict(zip(names.index, vectors))


def score_candidates(model: SentenceTransformer, data: pd.DataFrame, candidate_pairs: pd.DataFrame,
                     *, category: str, score_attrs: list[str], threshold: float,
                     rule_weight: float, embedding_weight: float, match_type: str,
                     name_col: str = "name_clean") -> pd.DataFrame:
    """Stage 2: combine rule score and embedding score, with per-pair explanation."""
    if candidate_pairs.empty:
        return pd.DataFrame()

    lookup = data.set_index("sku_id", drop=False)
    embeddings = embedding_scores(model, data, candidate_pairs, name_col=name_col)
    matches = []

    for _, pair in candidate_pairs.iterrows():
        left = lookup.loc[pair["sku_1"]]
        right = lookup.loc[pair["sku_2"]]
        rule_score, explanation = compare_hard_attrs(left, right, score_attrs)
        embedding_score = float(cosine_similarity([embeddings[pair["sku_1"]]], [embeddings[pair["sku_2"]]])[0][0])
        score = rule_score * rule_weight + embedding_score * embedding_weight

        # A hard mismatch in blocking-critical fields should not pass just because names are close.
        hard_mismatches = set(explanation["mismatched_fields"])
        if hard_mismatches & {"brand_clean", "width_clean", "profile_clean", "diameter_clean",
                              "viscosity_clean", "volume_clean", "capacity_clean", "voltage_clean"}:
            score *= 0.65

        explanation.update({
            "candidate_generation": {
                "rule": pair["candidate_rule"],
                "block_key": pair["candidate_block_key"],
            },
            "scoring": {
                "rule_score": round(rule_score, 3),
                "embedding_score": round(embedding_score, 3),
                "rule_weight": rule_weight,
                "embedding_weight": embedding_weight,
                "final_score": round(float(score), 3),
                "threshold": threshold,
            },
            "left": {
                "sku_id": pair["sku_1"],
                "source": pair["source_1"],
                "name": left.get("normalized_name"),
            },
            "right": {
                "sku_id": pair["sku_2"],
                "source": pair["source_2"],
                "name": right.get("normalized_name"),
            },
        })

        if score >= threshold:
            matches.append({
                "sku_1": pair["sku_1"],
                "sku_2": pair["sku_2"],
                "source_1": pair["source_1"],
                "source_2": pair["source_2"],
                "category": category,
                "score": round(float(score), 3),
                "rule_score": round(rule_score, 3),
                "embedding_score": round(embedding_score, 3),
                "match_type": match_type,
                "candidate_rule": pair["candidate_rule"],
                "candidate_block_key": pair["candidate_block_key"],
                "match_explanation": explanation,
            })
    return pd.DataFrame(matches)


def match_by_candidates(model: SentenceTransformer, data: pd.DataFrame, category: str,
                        *, name_col: str = "name_clean") -> pd.DataFrame:
    rules = CANDIDATE_RULES[category]
    candidates = generate_candidates(data, category, rules["block_attrs"])
    logger.info("%s candidates: %s", category, len(candidates))
    results = score_candidates(
        model,
        data,
        candidates,
        category=category,
        score_attrs=rules["score_attrs"],
        threshold=rules["threshold"],
        rule_weight=rules["rule_weight"],
        embedding_weight=rules["embedding_weight"],
        match_type=rules["match_type"],
        name_col=name_col,
    )
    logger.info("%s scored matches: %s", category, len(results))
    return results


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
            d = pd.read_sql(
                f"""
                SELECT DISTINCT ON ({q_ident("source")}, {q_ident("source_product_id")})
                    {columns_sql}
                FROM {q_ident(schema)}.{q_ident(table)}
                ORDER BY {q_ident("source")}, {q_ident("source_product_id")},
                         {q_ident("loaded_at")} DESC NULLS LAST
                """,
                engine,
            )
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

    tires_results = match_by_candidates(model, tires_df, "tires")
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

    oils_results = match_by_candidates(model, oils_df, "oils")
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

    # 1. exact OEM matches. This is still explicit candidate generation:
    # category + exact OEM, with a deterministic high score and explanation.
    oem_matches = []
    oem_df = filters_df[filters_df["oem_clean"] != "unknown"]
    for oem, group in oem_df.groupby("oem_clean"):
        if len(group) < 2 or group["source"].nunique() < 2:
            continue
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if group.iloc[i]["source"] == group.iloc[j]["source"]:
                    continue
                explanation = {
                    "candidate_generation": {
                        "rule": "category+oem_number",
                        "block_key": f"filters|{oem}",
                    },
                    "matched_fields": {
                        "oem_clean": {"left": oem, "right": oem},
                    },
                    "mismatched_fields": {},
                    "missing_fields": [],
                    "scoring": {
                        "rule_score": 1.0,
                        "embedding_score": None,
                        "rule_weight": 1.0,
                        "embedding_weight": 0.0,
                        "final_score": 1.0,
                        "threshold": 1.0,
                    },
                    "left": {
                        "sku_id": group.iloc[i]["sku_id"],
                        "source": group.iloc[i]["source"],
                        "name": group.iloc[i]["normalized_name"],
                    },
                    "right": {
                        "sku_id": group.iloc[j]["sku_id"],
                        "source": group.iloc[j]["source"],
                        "name": group.iloc[j]["normalized_name"],
                    },
                }
                oem_matches.append({
                    "sku_1": group.iloc[i]["sku_id"], "sku_2": group.iloc[j]["sku_id"],
                    "source_1": group.iloc[i]["source"], "source_2": group.iloc[j]["source"],
                    "category": "filters", "score": 1.0, "rule_score": 1.0,
                    "embedding_score": None, "match_type": "OEM",
                    "candidate_rule": "category+oem_number",
                    "candidate_block_key": f"filters|{oem}",
                    "match_explanation": explanation,
                })
    oem_results = pd.DataFrame(oem_matches).drop_duplicates(subset=["sku_1", "sku_2"])

    # 2. Fallback: candidate generation by category + brand + filter type,
    # scoring by hard attrs + embeddings.
    nlp_results = match_by_candidates(model, filters_df, "filters")

    filters_results = pd.concat([oem_results, nlp_results], ignore_index=True)
    if not filters_results.empty:
        filters_results = filters_results.sort_values("score", ascending=False).drop_duplicates(subset=["sku_1", "sku_2"])
    logger.info("Filter OEM matches: %s | NLP matches: %s | total: %s",
                len(oem_results), len(nlp_results), len(filters_results))
    return filters_df, filters_results


def match_batteries(df: pd.DataFrame, model: SentenceTransformer) -> tuple[pd.DataFrame, pd.DataFrame]:
    batteries_df = df[df["category"] == "batteries"].copy()

    batteries_df["capacity_clean"] = batteries_df["capacity_ah"].apply(clean_capacity)
    batteries_df["voltage_clean"] = batteries_df["voltage_v"].apply(clean_capacity)
    batteries_df["battery_type_clean"] = batteries_df["product_name"].apply(extract_battery_type).fillna("unknown").astype(str).str.lower()
    batteries_df["model_clean"] = batteries_df["name_clean"].apply(extract_battery_model)
    batteries_df["group_key"] = (
        batteries_df["brand_clean"] + "_" + batteries_df["model_clean"] + "_" + batteries_df["capacity_clean"]
    )

    batteries_results = match_by_candidates(model, batteries_df, "batteries")
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
        explanation = r.get("match_explanation")
        score, method = r["score"], r["match_type"]
        prev = pair_info.get(key)
        if prev is None or score > prev[0]:
            pair_info[key] = (score, method, explanation)

    mapping_records = []
    for members in all_components.values():
        anchor = all_group_root[members[0]]
        master_id = sku_id_map[anchor]

        for m in members:
            row = products_lookup.loc[m]
            if m == anchor:
                score, method = 1.0, "root" if len(members) > 1 else "single_source"
                explanation = {
                    "matched_fields": {},
                    "mismatched_fields": {},
                    "missing_fields": [],
                    "scoring": {
                        "rule_score": 1.0,
                        "embedding_score": None,
                        "final_score": 1.0,
                    },
                    "reason": "component anchor" if len(members) > 1 else "single source product",
                }
            else:
                best = None
                for other in members:
                    if other == m:
                        continue
                    info = pair_info.get(frozenset({m, other}))
                    if info and (best is None or info[0] > best[0]):
                        best = info
                if best:
                    score, method, explanation = best
                else:
                    score, method = 0.0, "rules+embeddings"
                    explanation = {"reason": "no direct pair found inside component"}

            mapping_records.append({
                "sku_id": master_id,
                "source": row["source"],
                "source_product_id": row["source_product_id"],
                "source_product_name": row["product_name"],
                "source_url": row["source_url"],
                "match_method": method,
                "match_score": round(float(score), 3),
                "match_confidence": confidence_bucket(score, method),
                "match_explanation": explanation,
            })

    sku_source_mapping = pd.DataFrame(mapping_records)
    logger.info("sku_source_mapping rows: %s", len(sku_source_mapping))
    return sku_source_mapping


def build_match_explanations(final_results: pd.DataFrame) -> pd.DataFrame:
    if final_results.empty:
        return pd.DataFrame(
            columns=[
                "sku_1", "sku_2", "source_1", "source_2", "category", "score",
                "rule_score", "embedding_score", "match_type", "candidate_rule",
                "candidate_block_key", "match_explanation",
            ]
        )
    columns = [
        "sku_1", "sku_2", "source_1", "source_2", "category", "score",
        "rule_score", "embedding_score", "match_type", "candidate_rule",
        "candidate_block_key", "match_explanation",
    ]
    present = [column for column in columns if column in final_results.columns]
    return final_results[present].copy()


def write_master_tables(
    engine: Engine,
    skus_df: pd.DataFrame,
    sku_source_mapping: pd.DataFrame,
    match_explanations: pd.DataFrame,
) -> None:
    schema = output_schema()
    suffix = uuid.uuid4().hex[:12]
    temp_tables = {
        "skus": f"_tmp_skus_{suffix}",
        "sku_source_mapping": f"_tmp_sku_source_mapping_{suffix}",
        "match_explanations": f"_tmp_match_explanations_{suffix}",
    }

    # source_id is already a list[dict]; let SQLAlchemy's JSONB type serialize it -
    # pre-encoding with json.dumps here would double-encode it into a JSON string column
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {q_ident(schema)}"))

    skus_df.to_sql(temp_tables["skus"], engine, schema=schema, if_exists="replace", index=False,
                    dtype={"source_id": JSONB}, method="multi", chunksize=5000)
    sku_source_mapping.to_sql(temp_tables["sku_source_mapping"], engine, schema=schema, if_exists="replace",
                               index=False, method="multi", chunksize=5000,
                               dtype={"match_explanation": JSONB})
    match_explanations.to_sql(temp_tables["match_explanations"], engine, schema=schema, if_exists="replace",
                              index=False, method="multi", chunksize=5000,
                              dtype={"match_explanation": JSONB})

    with engine.begin() as conn:
        # Downstream tables have foreign keys to skus/attributes and are rebuilt by the
        # following DAG tasks. Drop them only after all replacement matching tables exist.
        for table in [
            "match_explanations",
            "sku_attribute_values",
            "sku_price_history",
            "sku_source_mapping",
            "skus",
        ]:
            conn.execute(text(f"DROP TABLE IF EXISTS {q_ident(schema)}.{q_ident(table)} CASCADE"))
        for final_table, temp_table in temp_tables.items():
            conn.execute(
                text(
                    f"ALTER TABLE {q_ident(schema)}.{q_ident(temp_table)} "
                    f"RENAME TO {q_ident(final_table)}"
                )
            )
    logger.info(
        "Saved %s.skus, %s.sku_source_mapping and %s.match_explanations",
        schema, schema, schema,
    )


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
    )
    if not final_results.empty:
        final_results = final_results.sort_values("score", ascending=False).drop_duplicates(subset=["sku_1", "sku_2"])
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
    match_explanations = build_match_explanations(final_results)

    write_master_tables(engine, skus_df, sku_source_mapping, match_explanations)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = get_engine()
    run_pipeline(engine)


if __name__ == "__main__":
    main()
