--
-- PostgreSQL database dump
--

\restrict UviIFzoImeq1PwQMh5AMBVPdyDUGRPxl6N6KXzVT7B5eMEwjpuKjwagrSezs5pJ

-- Dumped from database version 15.18 (Debian 15.18-1.pgdg13+1)
-- Dumped by pg_dump version 15.18 (Debian 15.18-1.pgdg13+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: cleanned; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA cleanned;


--
-- Name: matching; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA matching;


--
-- Name: raw; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA raw;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: carcity_batteries; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.carcity_batteries (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    capacity_ah double precision,
    voltage_v double precision,
    start_current_a double precision,
    polarity text,
    battery_type text,
    dimensions text,
    terminal_type text,
    weight text,
    features text,
    length text,
    width text,
    height text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone
);


--
-- Name: carcity_filters; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.carcity_filters (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    filter_type text,
    compatible_brand text,
    compatible_model text,
    oem_number text,
    additional_information text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone
);


--
-- Name: carcity_oils; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.carcity_oils (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    viscosity text,
    volume_liters double precision,
    oil_type text,
    engine_type text,
    specification text,
    product_line text,
    package_type text,
    acea_class text,
    approvals text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone
);


--
-- Name: carcity_tires; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.carcity_tires (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    tire_width double precision,
    tire_profile double precision,
    tire_diameter double precision,
    season text,
    load_index text,
    speed_index text,
    studded boolean,
    runflat boolean,
    model_name text,
    weight text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone
);


--
-- Name: fdrive_batteries; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.fdrive_batteries (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    capacity_ah double precision,
    voltage_v double precision,
    start_current_a double precision,
    polarity text,
    battery_type text,
    dimensions text,
    terminal_type text,
    weight text,
    features text,
    length text,
    width text,
    height text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone
);


--
-- Name: fdrive_oils; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.fdrive_oils (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    viscosity text,
    volume_liters double precision,
    oil_type text,
    engine_type text,
    specification text,
    product_line text,
    package_type text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    acea_class text,
    approvals text
);


--
-- Name: fdrive_tires; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.fdrive_tires (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    tire_width double precision,
    tire_profile double precision,
    tire_diameter double precision,
    season text,
    load_index text,
    speed_index text,
    studded boolean,
    runflat boolean,
    model_name text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    weight text
);


--
-- Name: forte_market_batteries; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.forte_market_batteries (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    capacity_ah double precision,
    voltage_v double precision,
    start_current_a double precision,
    polarity text,
    battery_type text,
    dimensions text,
    terminal_type text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    weight text,
    features text,
    length text,
    width text,
    height text
);


--
-- Name: forte_market_filters; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.forte_market_filters (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    filter_type text,
    compatible_brand text,
    compatible_model text,
    oem_number text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    additional_information text
);


--
-- Name: forte_market_oils; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.forte_market_oils (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    viscosity text,
    volume_liters double precision,
    oil_type text,
    engine_type text,
    specification text,
    product_line text,
    package_type text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    acea_class text,
    approvals text
);


--
-- Name: forte_market_tires; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.forte_market_tires (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    tire_width double precision,
    tire_profile double precision,
    tire_diameter double precision,
    season text,
    load_index text,
    speed_index text,
    studded boolean,
    runflat boolean,
    model_name text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    weight text
);


--
-- Name: satu_batteries; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.satu_batteries (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    capacity_ah double precision,
    voltage_v double precision,
    start_current_a double precision,
    polarity text,
    battery_type text,
    dimensions text,
    terminal_type text,
    weight text,
    features text,
    length text,
    width text,
    height text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone
);


--
-- Name: satu_filters; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.satu_filters (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    filter_type text,
    compatible_brand text,
    compatible_model text,
    oem_number text,
    additional_information text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone
);


--
-- Name: satu_oils; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.satu_oils (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    viscosity text,
    volume_liters double precision,
    oil_type text,
    engine_type text,
    specification text,
    product_line text,
    package_type text,
    acea_class text,
    approvals text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone
);


--
-- Name: satu_tires; Type: TABLE; Schema: cleanned; Owner: -
--

CREATE TABLE cleanned.satu_tires (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price double precision,
    old_price double precision,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    tire_width double precision,
    tire_profile double precision,
    tire_diameter double precision,
    season text,
    load_index text,
    speed_index text,
    studded boolean,
    runflat boolean,
    model_name text,
    weight text,
    source_file text,
    loaded_at timestamp with time zone,
    load_id text,
    normalized_name text,
    cleaned_at timestamp with time zone
);


--
-- Name: attribute_groups; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.attribute_groups (
    id smallint NOT NULL,
    name text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL
);


--
-- Name: attributes; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.attributes (
    id smallint NOT NULL,
    name text NOT NULL,
    unit text,
    status text DEFAULT 'active'::text NOT NULL
);


--
-- Name: attributes_attribute_groups; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.attributes_attribute_groups (
    attribute_group_id smallint NOT NULL,
    attribute_group text NOT NULL,
    attribute_id smallint NOT NULL,
    attribute text NOT NULL
);


--
-- Name: categories; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.categories (
    category_id bigint NOT NULL,
    name text,
    level bigint,
    parent_category_id double precision,
    parent_category text,
    is_leaf boolean,
    status text
);


--
-- Name: category_attributes; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.category_attributes (
    category_id bigint NOT NULL,
    category text,
    attribute_group_id smallint,
    attribute_group text,
    attribute_id smallint NOT NULL,
    attribute text
);


--
-- Name: match_explanations; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.match_explanations (
    sku_1 text,
    sku_2 text,
    source_1 text,
    source_2 text,
    category text,
    score double precision,
    rule_score double precision,
    embedding_score double precision,
    match_type text,
    candidate_rule text,
    candidate_block_key text,
    match_explanation jsonb
);


--
-- Name: sku_attribute_values; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.sku_attribute_values (
    sku_id text NOT NULL,
    attribute_id smallint NOT NULL,
    attribute text,
    value text
);


--
-- Name: sku_price_history; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.sku_price_history (
    captured_at timestamp with time zone NOT NULL,
    price_date date,
    sku_id text,
    source text NOT NULL,
    source_product_id text NOT NULL,
    seller_name text,
    city text,
    price double precision,
    old_price double precision,
    discount_price double precision,
    currency text,
    availability text,
    parsed_at timestamp with time zone
);


--
-- Name: sku_source_mapping; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.sku_source_mapping (
    sku_id text,
    source text,
    source_product_id text,
    source_product_name text,
    source_url text,
    match_method text,
    match_score double precision,
    match_confidence text,
    match_explanation jsonb
);


--
-- Name: skus; Type: TABLE; Schema: matching; Owner: -
--

CREATE TABLE matching.skus (
    id text NOT NULL,
    name text,
    brand text,
    category_id bigint,
    normalized_description text,
    status text,
    source_id jsonb,
    is_szpt boolean
);


--
-- Name: _column_map; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw._column_map (
    table_name text NOT NULL,
    column_position integer NOT NULL,
    db_column_name text NOT NULL,
    source_column_name text NOT NULL
);


--
-- Name: _load_files; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw._load_files (
    load_id text NOT NULL,
    table_name text NOT NULL,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    row_count bigint
);


--
-- Name: carcity_batteries; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.carcity_batteries (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    capacity_ah text,
    voltage_v text,
    start_current_a text,
    polarity text,
    battery_type text,
    dimensions text,
    terminal_type text,
    weight text,
    features text,
    length text,
    width text,
    height text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL
);


--
-- Name: carcity_filters; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.carcity_filters (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    filter_type text,
    compatible_brand text,
    compatible_model text,
    oem_number text,
    additional_information text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL
);


--
-- Name: carcity_oils; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.carcity_oils (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    viscosity text,
    volume_liters text,
    oil_type text,
    engine_type text,
    specification text,
    product_line text,
    package_type text,
    acea_class text,
    approvals text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL
);


--
-- Name: carcity_tires; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.carcity_tires (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    tire_width text,
    tire_profile text,
    tire_diameter text,
    season text,
    load_index text,
    speed_index text,
    studded text,
    runflat text,
    model_name text,
    weight text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL
);


--
-- Name: fdrive_batteries; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.fdrive_batteries (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    capacity_ah text,
    voltage_v text,
    start_current_a text,
    polarity text,
    battery_type text,
    dimensions text,
    terminal_type text,
    weight text,
    features text,
    length text,
    width text,
    height text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL
);


--
-- Name: fdrive_oils; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.fdrive_oils (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    viscosity text,
    volume_liters text,
    oil_type text,
    engine_type text,
    specification text,
    product_line text,
    package_type text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    acea_class text,
    approvals text
);


--
-- Name: fdrive_tires; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.fdrive_tires (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    tire_width text,
    tire_profile text,
    tire_diameter text,
    season text,
    load_index text,
    speed_index text,
    studded text,
    runflat text,
    model_name text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    weight text
);


--
-- Name: forte_market_batteries; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.forte_market_batteries (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    capacity_ah text,
    voltage_v text,
    start_current_a text,
    polarity text,
    battery_type text,
    dimensions text,
    terminal_type text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    weight text,
    features text,
    length text,
    width text,
    height text
);


--
-- Name: forte_market_filters; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.forte_market_filters (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    filter_type text,
    compatible_brand text,
    compatible_model text,
    oem_number text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    additional_information text
);


--
-- Name: forte_market_oils; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.forte_market_oils (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    viscosity text,
    volume_liters text,
    oil_type text,
    engine_type text,
    specification text,
    product_line text,
    package_type text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    acea_class text,
    approvals text
);


--
-- Name: forte_market_tires; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.forte_market_tires (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    tire_width text,
    tire_profile text,
    tire_diameter text,
    season text,
    load_index text,
    speed_index text,
    studded text,
    runflat text,
    model_name text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    weight text
);


--
-- Name: satu_batteries; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.satu_batteries (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    capacity_ah text,
    voltage_v text,
    start_current_a text,
    polarity text,
    battery_type text,
    dimensions text,
    terminal_type text,
    weight text,
    features text,
    length text,
    width text,
    height text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL
);


--
-- Name: satu_filters; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.satu_filters (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    filter_type text,
    compatible_brand text,
    compatible_model text,
    oem_number text,
    additional_information text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL
);


--
-- Name: satu_oils; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.satu_oils (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    viscosity text,
    volume_liters text,
    oil_type text,
    engine_type text,
    specification text,
    product_line text,
    package_type text,
    acea_class text,
    approvals text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL
);


--
-- Name: satu_tires; Type: TABLE; Schema: raw; Owner: -
--

CREATE TABLE raw.satu_tires (
    source text,
    source_product_id text,
    source_url text,
    category_group text,
    product_name text,
    brand text,
    price text,
    old_price text,
    currency text,
    availability text,
    city text,
    image_url text,
    parsed_at text,
    article_sku text,
    rating text,
    reviews_count text,
    seller_count text,
    tire_width text,
    tire_profile text,
    tire_diameter text,
    season text,
    load_index text,
    speed_index text,
    studded text,
    runflat text,
    model_name text,
    weight text,
    source_file text NOT NULL,
    loaded_at timestamp with time zone DEFAULT now() NOT NULL,
    load_id text NOT NULL
);


--
-- Name: attribute_groups attribute_groups_name_key; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.attribute_groups
    ADD CONSTRAINT attribute_groups_name_key UNIQUE (name);


--
-- Name: attribute_groups attribute_groups_pkey; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.attribute_groups
    ADD CONSTRAINT attribute_groups_pkey PRIMARY KEY (id);


--
-- Name: attributes_attribute_groups attributes_attribute_groups_pkey; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.attributes_attribute_groups
    ADD CONSTRAINT attributes_attribute_groups_pkey PRIMARY KEY (attribute_group_id, attribute_id);


--
-- Name: attributes attributes_name_key; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.attributes
    ADD CONSTRAINT attributes_name_key UNIQUE (name);


--
-- Name: attributes attributes_pkey; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.attributes
    ADD CONSTRAINT attributes_pkey PRIMARY KEY (id);


--
-- Name: categories categories_pkey; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.categories
    ADD CONSTRAINT categories_pkey PRIMARY KEY (category_id);


--
-- Name: category_attributes category_attributes_pkey; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.category_attributes
    ADD CONSTRAINT category_attributes_pkey PRIMARY KEY (category_id, attribute_id);


--
-- Name: sku_attribute_values sku_attribute_values_pkey; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.sku_attribute_values
    ADD CONSTRAINT sku_attribute_values_pkey PRIMARY KEY (sku_id, attribute_id);


--
-- Name: skus skus_pkey; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.skus
    ADD CONSTRAINT skus_pkey PRIMARY KEY (id);


--
-- Name: sku_price_history uq_sph; Type: CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.sku_price_history
    ADD CONSTRAINT uq_sph UNIQUE (source, source_product_id, captured_at);


--
-- Name: _column_map _column_map_pkey; Type: CONSTRAINT; Schema: raw; Owner: -
--

ALTER TABLE ONLY raw._column_map
    ADD CONSTRAINT _column_map_pkey PRIMARY KEY (table_name, column_position);


--
-- Name: _load_files _load_files_pkey; Type: CONSTRAINT; Schema: raw; Owner: -
--

ALTER TABLE ONLY raw._load_files
    ADD CONSTRAINT _load_files_pkey PRIMARY KEY (load_id, table_name, source_file);


--
-- Name: idx_sav_attribute_id; Type: INDEX; Schema: matching; Owner: -
--

CREATE INDEX idx_sav_attribute_id ON matching.sku_attribute_values USING btree (attribute_id);


--
-- Name: ix_sph_cap; Type: INDEX; Schema: matching; Owner: -
--

CREATE INDEX ix_sph_cap ON matching.sku_price_history USING btree (source, source_product_id, captured_at);


--
-- Name: ix_sph_date; Type: INDEX; Schema: matching; Owner: -
--

CREATE INDEX ix_sph_date ON matching.sku_price_history USING btree (price_date);


--
-- Name: ix_sph_sku; Type: INDEX; Schema: matching; Owner: -
--

CREATE INDEX ix_sph_sku ON matching.sku_price_history USING btree (sku_id);


--
-- Name: attributes_attribute_groups attributes_attribute_groups_attribute_group_id_fkey; Type: FK CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.attributes_attribute_groups
    ADD CONSTRAINT attributes_attribute_groups_attribute_group_id_fkey FOREIGN KEY (attribute_group_id) REFERENCES matching.attribute_groups(id);


--
-- Name: attributes_attribute_groups attributes_attribute_groups_attribute_id_fkey; Type: FK CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.attributes_attribute_groups
    ADD CONSTRAINT attributes_attribute_groups_attribute_id_fkey FOREIGN KEY (attribute_id) REFERENCES matching.attributes(id);


--
-- Name: category_attributes category_attributes_attribute_group_id_fkey; Type: FK CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.category_attributes
    ADD CONSTRAINT category_attributes_attribute_group_id_fkey FOREIGN KEY (attribute_group_id) REFERENCES matching.attribute_groups(id);


--
-- Name: category_attributes category_attributes_attribute_id_fkey; Type: FK CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.category_attributes
    ADD CONSTRAINT category_attributes_attribute_id_fkey FOREIGN KEY (attribute_id) REFERENCES matching.attributes(id);


--
-- Name: category_attributes category_attributes_category_id_fkey; Type: FK CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.category_attributes
    ADD CONSTRAINT category_attributes_category_id_fkey FOREIGN KEY (category_id) REFERENCES matching.categories(category_id);


--
-- Name: sku_attribute_values sku_attribute_values_attribute_id_fkey; Type: FK CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.sku_attribute_values
    ADD CONSTRAINT sku_attribute_values_attribute_id_fkey FOREIGN KEY (attribute_id) REFERENCES matching.attributes(id);


--
-- Name: sku_attribute_values sku_attribute_values_sku_id_fkey; Type: FK CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.sku_attribute_values
    ADD CONSTRAINT sku_attribute_values_sku_id_fkey FOREIGN KEY (sku_id) REFERENCES matching.skus(id);


--
-- Name: sku_price_history sku_price_history_sku_id_fkey; Type: FK CONSTRAINT; Schema: matching; Owner: -
--

ALTER TABLE ONLY matching.sku_price_history
    ADD CONSTRAINT sku_price_history_sku_id_fkey FOREIGN KEY (sku_id) REFERENCES matching.skus(id);


--
-- PostgreSQL database dump complete
--

\unrestrict UviIFzoImeq1PwQMh5AMBVPdyDUGRPxl6N6KXzVT7B5eMEwjpuKjwagrSezs5pJ

